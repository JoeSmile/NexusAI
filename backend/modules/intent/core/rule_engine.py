"""
规则引擎 - 基于关键词的快速意图识别
Rule-Based Intent Engine for fast pattern matching
"""

from __future__ import annotations

from ..models.intent_models import IntentResult, IntentType


class RuleBasedIntentEngine:
    """基于规则的意图识别引擎（8 类 · Task 65 slice 8）"""

    INTENT_RULES: dict[IntentType, list[str]] = {
        IntentType.GREETING: [
            "你好", "您好", "哈喽", "嗨", "hello", "hi", "hey",
            "早上好", "中午好", "下午好", "晚上好", "大家好", "在吗",
        ],
        IntentType.AFTER_SALES: [
            "退款", "退货", "退钱", "换货", "发票", "投诉", "差评",
            "售后", "维修", "工单", "故障", "不好用", "升级处理",
        ],
        IntentType.PRE_SALES: [
            "产品介绍", "产品对比", "公司介绍", "报价", "售前", "报个价",
            "多少钱", "方案", "试用", "演示", "sku", "采购", "介绍一下", "对比",
        ],
        IntentType.KNOWLEDGE_QUERY: [
            "如何查询", "怎么查询", "查询公司", "公司的", "管理制度",
            "信息安全", "知识库", "制度", "政策", "规定", "流程是什么",
            "文档在哪", "sop", "合规", "内控", "报销流程", "请假制度",
        ],
        IntentType.CONTENT_ANALYSIS: [
            "热点挖掘", "选题", "竞品分析", "分析一下", "评估一下", "爆不爆",
            "数据洞察", "趋势", "这条内容", "竞争对手",
        ],
        IntentType.CONTENT_CREATION: [
            "口播", "脚本", "文案", "周报", "社媒", "短视频", "写个",
            "生成一篇", "创作", "热点文案",
        ],
        IntentType.FUNCTION: [
            "提醒我", "记得", "别忘了", "设置闹钟", "定时",
            "记录", "保存", "备忘", "日程", "帮我记", "创建提醒", "添加事项",
        ],
        IntentType.CONVERSATION: [
            "你是谁", "谢谢", "再见", "拜拜", "哈哈", "聊聊",
            "然后呢", "接着说", "嗯嗯", "懂了",
            # 08-25：问模型归属（"你使用的是什么模型"）→ 身份询问，归会话（与"你是谁"一致）
            # 完整短语匹配，避免单字"模型"误伤售前（"大模型平台"类）
            "你使用的是什么模型", "你们用的什么模型", "你用的什么模型",
            "用什么模型", "哪个大模型", "什么大模型",
        ],
    }

    def detect_intent(self, text: str) -> IntentResult | None:
        text = text.lower().strip()
        if not text:
            return None

        for intent, keywords in self.INTENT_RULES.items():
            matched = [kw for kw in keywords if kw in text]
            if matched:
                confidence = min(0.8 + len(matched) * 0.05, 1.0)
                return IntentResult(
                    intent=intent,
                    confidence=confidence,
                    source="rule",
                    metadata={"matched_keywords": matched},
                )
        return None

    def get_matched_keywords(self, text: str, intent: IntentType) -> list[str]:
        text = text.lower()
        keywords = self.INTENT_RULES.get(intent, [])
        return [kw for kw in keywords if kw in text]
