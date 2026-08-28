"""Template-based hard cases + optional LLM expansion (Task 65 slice 1/8)."""

from __future__ import annotations

import random

from packages.intent.core.label_map import normalize_sample
from packages.intent.core.rule_engine import RuleBasedIntentEngine
from packages.intent.models.intent_models import IntentType

from .io import IntentSample

# 8-class seed templates (Task 65 slice 8 business L0)
_SEED: dict[str, list[str]] = {
    "greeting": [
        "你好", "您好", "嗨", "哈喽", "hello", "hi", "早上好", "下午好", "晚上好",
        "大家好", "拜拜", "再见", "回头聊", "嗨喽", "在吗", "你好呀", "hi 早上好",
        "哈喽你好", "大家好呀", "下午好呀", "老板好", "老师好",
    ],
    "pre_sales": [
        "介绍一下产品", "和竞品对比一下", "公司介绍发我", "帮我报个价", "做个方案报价",
        "产品有哪些功能", "和友商比有什么优势", "演示一下系统", "售前咨询一下",
        "这个 SKU 多少钱", "能给个报价单吗", "产品对比表有吗", "公司简介在哪看",
        "想了解一下你们的产品", "能给个 demo 吗", "方案报价大概多少",
    ],
    "after_sales": [
        "怎么退款", "我要投诉", "发票怎么开", "产品故障了怎么办", "售后电话多少",
        "退货流程是什么", "换货要多久", "维修进度查一下", "工单怎么提交",
        "退款多久到账", "投诉升级找谁", "发票抬头错了怎么改", "保修期还有多久",
        "设备坏了能上门吗", "售后政策是什么", "我要申请退款",
    ],
    "content_creation": [
        "帮我写个口播稿", "生成一篇热点文案", "写个短视频脚本", "帮我写周报",
        "写个社媒文案", "生成口播脚本", "写个朋友圈文案", "帮我创作一条短视频文案",
        "口播稿怎么写", "帮我生成周报模板", "写个热点口播", "社媒内容帮我写一下",
    ],
    "content_analysis": [
        "分析一下这个热点", "帮我做个选题", "帮我梳理一下这个热点事件",
        "这个选题值不值得做", "这个热点值不值得追", "帮我分析下竞争对手",
        "这条内容爆不爆得了", "竞品洞察报告", "热点挖掘一下", "评估一下这个选题",
        "分析一下竞品数据", "这个趋势怎么看", "帮我评估一下风险",
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
        "收藏这篇文章", "添加到待办", "帮我查一下明天的日程", "设置每周五提醒",
        "翻译这段话", "总结这篇文章", "发一封邮件给客户", "帮我订个会议室",
    ],
    "conversation": [
        "今天天气不错", "周末去哪玩", "你叫什么名字", "讲个笑话", "今天股票涨了吗",
        "最近有什么好看的电影", "晚饭吃什么好", "你吃饭了吗", "今天好累啊",
        "随便聊聊", "你觉得 AI 会取代人吗", "今天新闻有啥大事", "放假想去哪玩",
        "好无聊啊", "你平时都干嘛", "最近健身效果不错", "新买的键盘真不错",
        "新来的同事叫什么名字", "老板今天心情怎么样", "食堂今天吃什么", "最近在追什么剧",
        "明天会不会下雨", "油价又涨了", "周末要不要一起去打球", "你有没有听过那首歌",
        "然后呢", "接着说", "嗯嗯继续", "明白了", "原来是这样", "有意思", "详细说说",
        "再讲具体一点", "还有吗", "然后呢然后呢", "懂了懂了", "好的你继续",
        "嗯嗯", "展开讲讲", "能不能再举个例子",
        "帮我想想怎么提高效率", "有什么建议吗", "我应该怎么处理这件事",
        "你觉得怎么做比较好", "给个建议", "帮我想个办法", "我该选哪个方案",
    ],
}

_VARIANTS: dict[str, list[str]] = {
    "default": ["{}", "请问{}", "{}啊", "{}呀", "{}吧", "帮我{}", "我想{}"],
}

_HARD_MIX: list[tuple[str, str]] = [
    ("你好，公司报销流程是什么", "knowledge_query"),
    ("在吗，帮我记一下明天开会", "function"),
    ("谢谢，然后呢", "conversation"),
    ("嗨，帮我报个价", "pre_sales"),
    ("哈喽，怎么退款", "after_sales"),
    ("帮我写个口播稿", "content_creation"),
    ("分析一下竞品", "content_analysis"),
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
        label = normalize_sample(text, row["label"])
        rule = engine.detect_intent(text)
        if rule and rule.intent.value == label and rule.confidence >= 0.8:
            out.append({**row, "label": label, "label_source": "synthetic_validated"})
        elif label in {IntentType.CONVERSATION.value}:
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
            label = normalize_sample(text, str(obj.get("label", "")))
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
