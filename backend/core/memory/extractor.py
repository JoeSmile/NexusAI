"""记忆抽取抽象 — Task 41 · Slice 2（零 LLM 先行）。

决策（2026-08-06 拍板）:langmem 实测不兼容（需 langchain-openai>=0.3.1，
本项目锁 <0.2.0）→ 不引入；走 ``PostgresStore 语义检索 + 自研抽取``。
抽取分层:

- ``MEMORY_EXTRACTOR=rule``（默认）: 零 LLM 规则抽取，只吃高置信度句式
  （显式"记住 X" + 强偏好/身份句式），保守优先，宁缺勿滥。
- ``MEMORY_EXTRACTOR=small_model``（预留）: ``SmallModelExtractor`` 接口已留，
  实现未完成前工厂回退 rule 并告警；构造参数收 harness 模型实例（EVID-08）。

写路径（write_memory 节点）调用 ``get_extractor().extract(...)``，
候选经 ``UnifiedMemoryService.write(tier="warm", ...)`` 落库（upsert by key）。
抽取失败绝不阻塞管线（零 LLM 阶段尤其要静默）。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_DEFAULT_MIN_CONFIDENCE = 0.6

# 显式记忆命令：记住/请记住/记得
_RE_REMEMBER = re.compile(r"(?:请)?(?:记住|记得)[:：]?\s*(.{1,120})")
# 偏好句式：我喜欢/不喜欢/偏好/偏爱/习惯 …
_RE_PREFERENCE = re.compile(r"(?:我|用户)\s*(喜欢|不喜欢|偏好|偏爱|习惯)\s*(.{1,40})")
# 身份句式：我叫/我是 …
_RE_IDENTITY = re.compile(r"(?:我|用户)\s*(?:叫|是)\s*(.{1,20})")

_RE_STRIP = re.compile(r"[，。！？、\s]+")
_RE_PARTICLE_TRAIL = re.compile(r"[啊呀哦嘛咯嘿诶]+$")

# 口语/否定/疑问拦截（Finding 1 拍板 B；语气词 3A）
_FILLER_PREFIX = ("不是", "是不是", "说", "觉得", "想", "在", "做", "干", "搞", "是", "你", "他", "她")
_FILLER_SUFFIX = (
    "吗",
    "呢",
    "吧",
    "的",
    "了",
    "说",
    "想",
    "在",
    "是",
    "过",
    "做",
    "干",
    "这样",
    "那样",
    "啊",
    "呀",
    "哦",
    "嘛",
    "咯",
    "嘿",
    "诶",
)
_QUESTION_WORDS = ("谁", "什么", "怎么", "是不是", "为什么")

# 角色/籍贯后缀与职衔（1B + 本轮 2A/3A：去理/生防误杀真名；加籍/裔与职衔）
_ROLE_SUFFIX = ("人", "员", "师", "家", "长", "官", "工", "手", "者", "籍", "裔")
_ROLE_TITLES = (
    "程序员",
    "工程师",
    "经理",
    "管理员",
    "老板",
    "老师",
    "学生",
    "医生",
    "律师",
    "会计",
    "司机",
    "开发",
    "测试",
    "产品",
    "运营",
    "总监",
    "主管",
    "实习生",
    "助理",
    "护理",
    "护士",
    "顾问",
    "导演",
    "编辑",
    "记者",
    "设计师",
    "分析师",
)

# 敏感/越权闸门（2A + 本轮 1A/4A：中英密码；记住/偏好/身份共用）
_UNSAFE_FACT = re.compile(
    r"(密码|口令|密钥|私钥|api\s*key|access\s*token|secret|bearer|sk-[a-z0-9]|"
    r"password|passwd|\bpwd\b|"
    r"忽略以上|忽略之前|忽略前述|ignore\s+previous|system\s*prompt|"
    r"你现在是|jailbreak)",
    re.IGNORECASE,
)


def _strip_particles(value: str) -> str:
    """剥尾语气词：我叫李四啊 → 李四。"""
    return _RE_PARTICLE_TRAIL.sub("", value).strip()


def _is_role_or_nationality(value: str) -> bool:
    if any(t in value for t in _ROLE_TITLES):
        return True
    return value.endswith(_ROLE_SUFFIX)


def _is_safe_fact(value: str) -> bool:
    """拒敏感秘密与指令覆盖类文案（记住 / 偏好 / 身份共用）。"""
    if len(value) < 2 or len(value) > 120:
        return False
    if "\x00" in value:
        return False
    return _UNSAFE_FACT.search(value) is None


def _is_clean_name(value: str) -> bool:
    """身份值校验：2-8 字纯中文，排除口语/角色籍贯/疑问/敏感词。"""
    value = _strip_particles(value)
    if not (2 <= len(value) <= 8):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fa5]+", value):
        return False
    if value.startswith(_FILLER_PREFIX):
        return False
    if value.endswith(_FILLER_SUFFIX):
        return False
    if _is_role_or_nationality(value):
        return False
    if not _is_safe_fact(value):
        return False
    return not any(w in value for w in _QUESTION_WORDS)


def _is_clean_pref(value: str) -> bool:
    """偏好宾语：≥2 字、非口语结尾、过安全闸门。"""
    value = _strip_particles(value)
    if len(value) < 2 or value.endswith(_FILLER_SUFFIX):
        return False
    return _is_safe_fact(value)


@dataclass
class MemoryCandidate:
    """一条待落库的 warm 记忆候选。"""

    key: str  # 稳定键（同事实重复说 → 同 key，upsert 去重）
    value: str
    confidence: float
    source: str = "rule"


class MemoryExtractor(Protocol):
    """抽取器协议；small_model 实现须兼容此签名。"""

    async def extract(
        self,
        *,
        user_message: str,
        assistant_message: str | None = None,
    ) -> list[MemoryCandidate]: ...


def _slug(text: str, limit: int = 12) -> str:
    """稳定短 slug（去空白标点，截断）。"""
    return _RE_STRIP.sub("", text)[:limit]


class RuleExtractor:
    """零 LLM 规则抽取 — 保守优先，只吃高置信度句式。"""

    async def extract(
        self,
        *,
        user_message: str,
        assistant_message: str | None = None,
    ) -> list[MemoryCandidate]:
        del assistant_message  # 零 LLM 阶段只看用户侧；小模型阶段可扩展
        text = (user_message or "").strip()
        if not text:
            return []

        found: list[MemoryCandidate] = []
        remembers = list(_RE_REMEMBER.finditer(text))
        if remembers:
            # 显式"记住 X"是最高权威命令：命中则只取它，避免同句双写
            for m in remembers:
                phrase = m.group(1).strip()
                if not _is_safe_fact(phrase):
                    continue
                found.append(
                    MemoryCandidate(
                        key=f"fact:{_slug(phrase)}",
                        value=phrase,
                        confidence=0.9,
                    )
                )
            return found
        for m in _RE_PREFERENCE.finditer(text):
            verb, obj = m.group(1), _strip_particles(m.group(2).strip())
            if not _is_clean_pref(obj):
                continue
            found.append(
                MemoryCandidate(
                    key=f"preference:{_slug(verb + obj)}",
                    value=f"{verb}{obj}",
                    confidence=0.7,
                )
            )
        for m in _RE_IDENTITY.finditer(text):
            name = _strip_particles(m.group(1).strip())
            if not _is_clean_name(name):
                continue
            found.append(
                MemoryCandidate(
                    key=f"identity:{_slug(name)}",
                    value=f"叫{name}",
                    confidence=0.85,
                )
            )
        # 去重（同句多模式命中同一事实时取置信度最高者）
        best: dict[str, MemoryCandidate] = {}
        for c in found:
            prev = best.get(c.key)
            if prev is None or c.confidence > prev.confidence:
                best[c.key] = c
        return list(best.values())


class SmallModelExtractor:
    """预留：小模型抽取（Qwen2.5-7B 级 + 约束解码）。

    构造参数收 harness 模型实例；未实现完成前工厂回退 rule。
    """

    def __init__(self, model: Any = None, schema: dict | None = None) -> None:
        self.model = model
        self.schema = schema

    async def extract(
        self,
        *,
        user_message: str,
        assistant_message: str | None = None,
    ) -> list[MemoryCandidate]:
        raise NotImplementedError("small_model extractor not implemented; fallback to rule")


def min_confidence() -> float:
    try:
        return float(os.getenv("MEMORY_EXTRACT_MIN_CONFIDENCE", str(_DEFAULT_MIN_CONFIDENCE)))
    except ValueError:
        return _DEFAULT_MIN_CONFIDENCE


def get_extractor() -> MemoryExtractor:
    """工厂：``MEMORY_EXTRACTOR=rule|small_model``。

    small_model 需显式配置模型（``MEMORY_EXTRACTOR_MODEL``，如 qwen2.5:7b）；
    未配置或实现未完成 → 回退 rule 并告警（宁缺勿滥，不让抽取静默失效）。
    """
    mode = os.getenv("MEMORY_EXTRACTOR", "rule").strip().lower()
    if mode == "small_model":
        model_ref = os.getenv("MEMORY_EXTRACTOR_MODEL", "").strip()
        if model_ref:
            logger.warning(
                "small_model extractor 尚未实现（model=%s）；本次回退 rule", model_ref
            )
        else:
            logger.warning(
                "MEMORY_EXTRACTOR=small_model 但未设 MEMORY_EXTRACTOR_MODEL；回退 rule"
            )
    return RuleExtractor()


__all__ = [
    "MemoryCandidate",
    "MemoryExtractor",
    "RuleExtractor",
    "SmallModelExtractor",
    "get_extractor",
    "min_confidence",
]
