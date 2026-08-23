"""Template-based hard cases + optional LLM expansion (Task 65 slice 1)."""

from __future__ import annotations

import random

from backend.modules.intent.core.label_map import normalize_label
from backend.modules.intent.core.rule_engine import RuleBasedIntentEngine
from backend.modules.intent.models.intent_models import IntentType

from .io import IntentSample

# Full 7-class seed templates (from intent_project/gen_nexusai_seed.py)
_SEED: dict[str, list[str]] = {
    "greeting": [
        "你好", "您好", "嗨", "哈喽", "hello", "hi", "早上好", "下午好", "晚上好",
        "大家好", "拜拜", "再见", "回头聊", "嗨喽", "在吗", "你好呀", "hi 早上好",
        "哈喽你好", "大家好呀", "下午好呀", "老板好", "老师好",
    ],
    "knowledge_query": [
        "公司报销流程是什么", "差旅报销怎么走流程", "查一下请假制度", "员工请假几天要审批",
        "绩效考核流程是什么", "年终奖怎么算的", "公司管理制度在哪里看", "合规要求有哪些",
        "入职第一天要做什么", "会议室怎么预订", "出差标准是多少", "加班费怎么算",
        "年假有几天", "社保怎么交的", "公司培训安排", "转正流程是什么",
        "查一下公司规定", "报销发票有什么要求", "办公用品怎么申请", "IT 支持电话多少",
        "离职流程怎么走", "调休怎么申请", "工资条怎么看", "体检福利有吗",
        "公司食堂在哪", "班车路线", "工牌丢了怎么办", "邮箱密码忘了怎么办",
        "新员工培训什么时候", "数据安全红线是什么",
    ],
    "function": [
        "帮我记一下明天十点开会", "创建提醒", "提醒我下午喝水", "帮我设个闹钟七点",
        "保存这条消息", "备忘一下", "记录一下今天的任务", "别忘了周五交周报",
        "帮我写个口播稿", "生成一篇热点文案", "分析一下这个热点", "写个考研选题脚本",
        "帮我做个选题", "生成口播脚本", "写个短视频文案", "帮我梳理一下这个热点事件",
        "收藏这篇文章", "添加到待办", "帮我查一下明天的日程", "设置每周五提醒",
        "翻译这段话", "总结这篇文章", "把这段文字转成口播稿",
    ],
    "advice": [
        "帮我想想怎么提高效率", "有什么建议吗", "我应该怎么处理这件事", "推荐一下方案",
        "帮我分析一下这个情况", "提点意见", "你觉得怎么做比较好", "给个建议",
        "帮我想个办法", "怎么跟客户沟通比较好", "这个选题值不值得做", "帮我权衡一下",
        "我该选哪个方案", "有什么改进建议", "帮我想想怎么回复他",
        "你觉得我该不该跳槽", "这个热点值不值得追", "要不要换个方向做", "帮我分析下这个数据",
        "这个方案可行吗", "我该怎么选", "帮我评估一下风险", "给点职业建议",
        "你看这个情况怎么办", "帮我拿个主意", "这条内容爆不爆得了", "帮我分析下竞争对手",
    ],
    "chat": [
        "今天天气不错", "周末去哪玩", "你叫什么名字", "讲个笑话", "今天股票涨了吗",
        "最近有什么好看的电影", "晚饭吃什么好", "你吃饭了吗", "今天好累啊",
        "随便聊聊", "你觉得 AI 会取代人吗", "今天新闻有啥大事", "放假想去哪玩",
        "好无聊啊", "你平时都干嘛", "最近健身效果不错", "新买的键盘真不错",
        "新来的同事叫什么名字", "老板今天心情怎么样", "食堂今天吃什么", "最近在追什么剧",
        "明天会不会下雨", "油价又涨了", "周末要不要一起去打球", "你有没有听过那首歌",
    ],
    "conversation": [
        "然后呢", "接着说", "嗯嗯继续", "明白了", "原来是这样", "有意思", "详细说说",
        "再讲具体一点", "还有吗", "然后呢然后呢", "懂了懂了", "好的你继续",
        "嗯嗯", "展开讲讲", "能不能再举个例子",
    ],
    "crisis": [
        "我不想活了", "活着太累了", "撑不下去了", "我想结束生命", "活着没意思",
        "不想继续了", "好想解脱", "我很难受，帮帮我", "我很绝望", "撑不住怎么办",
        "感觉人生没有意义", "我想离开这个世界", "太痛苦了", "活着好痛苦",
        "我坚持不下去了", "我好想消失", "没有人理解我，我真的撑不住了",
        "我是不是不该存在", "活着太辛苦了", "我想睡过去再也不醒来",
        "我真的扛不住了", "能不能带我走", "我受够了这一切",
        "我熬不过今晚了", "我不想再醒来了", "我太累了，想休息一辈子",
        "帮帮我，我不知道该怎么办了", "我现在只想结束这一切",
        "感觉自己要被压垮了", "我撑不下去了，好想放弃一切",
    ],
}

_VARIANTS: dict[str, list[str]] = {
    "crisis": [],
    "default": ["{}", "请问{}", "{}啊", "{}呀", "{}吧", "帮我{}", "我想{}"],
}

_HARD_MIX: list[tuple[str, str]] = [
    ("你好，公司报销流程是什么", "knowledge_query"),
    ("在吗，帮我记一下明天开会", "function"),
    ("谢谢，然后呢", "conversation"),
    ("嗨，有什么建议吗", "advice"),
    ("哈喽，今天天气不错", "chat"),
]


def _expand_templates(*, seed: int = 42) -> list[IntentSample]:
    rng = random.Random(seed)
    rows: list[IntentSample] = []
    for label, samples in _SEED.items():
        for text in samples:
            rows.append({"text": text, "label": label, "label_source": "synthetic"})
            variants = _VARIANTS.get(label, _VARIANTS["default"])
            if not variants:
                continue
            for tpl in rng.sample(variants, k=min(3, len(variants))):
                variant = tpl.format(text)
                if variant != text and len(variant) <= 60:
                    rows.append(
                        {
                            "text": variant,
                            "label": label,
                            "label_source": "synthetic",
                        }
                    )
    for text, label in _HARD_MIX:
        rows.append({"text": text, "label": label, "label_source": "synthetic_hard"})
    return rows


def _rule_validated(samples: list[IntentSample]) -> list[IntentSample]:
    engine = RuleBasedIntentEngine()
    out: list[IntentSample] = []
    for row in samples:
        text = row["text"]
        label = normalize_label(row["label"])
        rule = engine.detect_intent(text)
        if rule and rule.intent.value == label and rule.confidence >= 0.8:
            out.append({**row, "label": label, "label_source": "synthetic_validated"})
        elif label in {IntentType.CRISIS.value, IntentType.CONVERSATION.value}:
            # crisis/conversation may not keyword-match; keep template labels
            out.append({**row, "label": label})
    return out


def generate_synthetic_hardcases(
    *,
    seed: int = 42,
    validate_with_rules: bool = False,
) -> list[IntentSample]:
    rows = _expand_templates(seed=seed)
    if validate_with_rules:
        validated = _rule_validated(rows)
        if validated:
            return validated
    return rows


def generate_llm_hardcases(
    *,
    per_intent: int = 10,
) -> list[IntentSample]:
    """Optional LLM expansion — returns [] when harness unavailable."""
    try:
        from backend.core.harness import LLMHarness
    except Exception:
        return []

    harness = LLMHarness()
    labels = [i.value for i in IntentType]
    prompt = (
        "生成中文口语意图训练样本。每行 JSON: "
        '{"text":"...", "label":"..."}。'
        f"label 只能是: {', '.join(labels)}。"
        f"每类 {per_intent} 条，口语化/省略/多意图混合。"
    )
    try:
        resp = harness.generate(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            tenant_id="system",
            api_key="",
            base_url="",
        )
    except Exception:
        return []

    import json

    out: list[IntentSample] = []
    for line in (resp or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            text = str(obj.get("text", "")).strip()
            label = normalize_label(str(obj.get("label", "")))
            if text:
                out.append(
                    {
                        "text": text,
                        "label": label,
                        "label_source": "llm_synthetic",
                    }
                )
        except json.JSONDecodeError:
            continue
    return out
