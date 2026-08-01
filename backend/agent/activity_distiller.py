"""
Activity Distiller — 活动蒸馏管道

参考 ai-buddy Phase 6.3 六层记忆架构设计，适配 ContextGate 场景。

后台蒸馏管道：每轮对话结束后，将 L2 活动日志浓缩到 L3 用户偏好。
  - 不调用 LLM，纯聚合计算
  - 幂等：相同输入 → 相同 content_sha256
  - 失败静默：任何错误仅 log，不影响主流程

蒸馏输出（稳定路径）：
  L3 user store:
      path = "preferences/recent_topics"
      content = JSON [{topic, freq, last_seen}, ...]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

RECENT_TOPICS_LIMIT = 20

PREFS_TOPICS_PATH = "preferences/recent_topics"


# ── TurnDigest ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TurnDigest:
    """一轮对话的蒸馏输入数据"""
    session_id: str
    user_id: str
    query: str                     # 用户消息
    timestamp: float               # Unix timestamp
    tool_calls: list[dict[str, Any]] = ()  # [{name, success}]
    final_status: str = "success"  # success / failed / timeout


# ── 聚合函数（纯函数，无副作用） ──────────────────────────────────────────────

def _extract_topic(query: str) -> str:
    """启发式话题提取 — 取前50字符，规范化空白"""
    if not query:
        return ""
    cleaned = " ".join(query.split())
    return cleaned[:50]


def merge_recent_topics(prior_json: str | None, digest: TurnDigest) -> str:
    """合并新话题到已有列表，去重并排序。

    Returns: canonical JSON (sort_keys, separators) 保证幂等 sha256。
    """
    items: list[dict[str, Any]] = []
    if prior_json:
        try:
            parsed = json.loads(prior_json)
            if isinstance(parsed, list):
                items = [x for x in parsed if isinstance(x, dict)]
        except (json.JSONDecodeError, TypeError):
            items = []

    topic = _extract_topic(digest.query)
    if not topic:
        return prior_json or ""

    # 已存在则更新频率和最后时间，否则插入
    found = False
    for entry in items:
        if entry.get("topic") == topic:
            entry["freq"] = int(entry.get("freq", 0)) + 1
            entry["last_seen"] = digest.timestamp
            found = True
            break
    if not found:
        items.insert(0, {
            "topic": topic,
            "freq": 1,
            "last_seen": digest.timestamp,
        })

    # 按最后出现时间降序，保留上限
    items.sort(key=lambda x: x.get("last_seen", 0), reverse=True)
    items = items[:RECENT_TOPICS_LIMIT]

    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ── 公共入口 ──────────────────────────────────────────────────────────────────

async def distill_turn(
    digest: TurnDigest,
    *,
    user_store: Any | None = None,
    agent_instance_store: Any | None = None,
) -> dict[str, bool]:
    """蒸馏一轮对话到 L3/L4 store。

    Args:
        digest: TurnDigest 数据
        user_store: L3 MemoryStore（用户作用域）
        agent_instance_store: L4 MemoryStore（Agent 实例作用域，暂保留参数兼容）

    Returns:
        {"topics_updated": bool}
    """
    result = {
        "topics_updated": False,
    }

    # ── L3: 用户偏好 ────────────────────────────────────────────────────
    if user_store is not None:
        # 话题偏好
        try:
            existing = await user_store.read(PREFS_TOPICS_PATH)
            prior = existing.content if existing else None
            new_content = merge_recent_topics(prior, digest)
            if new_content and new_content != (prior or ""):
                await user_store.write(PREFS_TOPICS_PATH, new_content)
                result["topics_updated"] = True
        except Exception as exc:
            logger.warning("distill_turn(L3 topics) failed: %s", exc)

    # ── L4: Agent 实例模式（预留，待后续模式蒸馏）──
    if agent_instance_store is not None:
        logger.debug(
            "distill_turn: agent_instance_store 预留，暂无可蒸馏模式 (session=%s)",
            digest.session_id[:8],
        )

    updated = [k for k, v in result.items() if v]
    if updated:
        logger.info(
            "distill_turn: session=%s, user=%s, updated=%s",
            digest.session_id[:8], digest.user_id[:8], updated,
        )
    return result
