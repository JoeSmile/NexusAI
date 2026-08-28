"""
意图识别服务
Intent Recognition Service
"""

import logging
from typing import Any

from ..core.input_processor import InputProcessor
from ..core.intent_classifier import IntentClassifier
from ..models.intent_models import IntentResult

logger = logging.getLogger(__name__)


class IntentService:
    """
    意图识别服务
    整合输入处理、意图识别等功能
    """
    
    def __init__(self, model_path: str | None = None):
        """
        初始化意图识别服务
        
        Args:
            model_path: ML模型路径（可选）
        """
        self.input_processor = InputProcessor()
        self.intent_classifier = IntentClassifier(model_path)
        logger.info("意图识别服务初始化完成")
    
    def analyze(self, text: str, user_id: str | None = None) -> dict[str, Any]:
        """
        分析用户输入的意图
        
        Args:
            text: 用户输入文本
            user_id: 用户ID（可选）
            
        Returns:
            分析结果字典，包含：
            - processed: 预处理结果
            - intent: 意图识别结果
            - action_required: 是否需要特殊行动
            - suggestion: 建议的响应策略
        """
        # 1. 输入预处理
        processed = self.input_processor.preprocess(text)
        
        # 2. 如果输入被阻止，直接返回
        if processed["blocked"]:
            return {
                "success": False,
                "processed": processed,
                "intent": None,
                "action_required": False,
                "suggestion": "输入不合规，请修改后重试"
            }
        
        # 3. 意图识别
        intent_result = self.intent_classifier.detect_intent(processed["cleaned"])
        
        # 4. 生成响应建议
        suggestion = self._generate_suggestion(intent_result, processed)
        
        # 5. 判断是否需要特殊行动
        action_required = self._check_action_required(intent_result, processed)
        
        result = {
            "success": True,
            "processed": processed,
            "intent": intent_result.model_dump(),
            "action_required": action_required,
            "suggestion": suggestion
        }
        
        # 记录日志
        if action_required:
            logger.warning(
                f"用户 {user_id} 需要特殊关注 - 意图: {intent_result.intent}, "
                f"风险等级: {processed['risk_level']}"
            )
        
        return result
    
    def _generate_suggestion(
        self, 
        intent_result: IntentResult, 
        processed: dict[str, Any]
    ) -> dict[str, Any]:
        """
        根据意图生成响应建议
        
        Args:
            intent_result: 意图识别结果
            processed: 预处理结果
            
        Returns:
            响应建议字典
        """
        from ..models.intent_models import IntentType
        
        # 根据不同意图类型提供不同的响应策略
        suggestions = {
            IntentType.GREETING: {
                "response_style": "友好、简短",
                "priority": "low",
                "actions": ["寒暄回应"],
                "avoid": ["冗长"],
                "prompt_hint": "问候模式：短路径 greeting skill",
            },
            IntentType.PRE_SALES: {
                "response_style": "专业、价值导向",
                "priority": "high",
                "actions": ["产品介绍", "方案对比", "报价说明"],
                "avoid": ["编造价格", "过度承诺"],
                "prompt_hint": "售前模式：走售前 Agent / quote_proposal",
            },
            IntentType.AFTER_SALES: {
                "response_style": "合规、安抚、可执行",
                "priority": "high",
                "actions": ["政策查表", "工单升级", "时效说明"],
                "avoid": ["擅自承诺退款"],
                "prompt_hint": "售后模式：refund_policy / complaint_escalation 短路径或售后 Agent",
            },
            IntentType.CONTENT_CREATION: {
                "response_style": "创意、结构化",
                "priority": "medium",
                "actions": ["生成脚本/文案/周报"],
                "avoid": ["抄袭", "违规表述"],
                "prompt_hint": "内容创作模式：内容 Agent + 对应 skill",
            },
            IntentType.CONTENT_ANALYSIS: {
                "response_style": "分析、客观",
                "priority": "medium",
                "actions": ["热点/竞品/选题分析"],
                "avoid": ["无依据结论"],
                "prompt_hint": "内容分析模式：分析 Agent + hotspot.dig",
            },
            IntentType.KNOWLEDGE_QUERY: {
                "response_style": "专业、准确、可溯源",
                "priority": "high",
                "actions": [
                    "检索企业知识库",
                    "引用制度/政策原文要点",
                    "标明出处",
                ],
                "avoid": ["编造制度", "情感化安慰"],
                "prompt_hint": "知识查询模式：优先 RAG/知识库",
            },
            IntentType.FUNCTION: {
                "response_style": "高效、明确、友好",
                "priority": "medium",
                "actions": ["确认需求", "执行功能", "反馈结果"],
                "avoid": ["冗长", "模糊"],
                "prompt_hint": "功能执行模式：工具/提醒/记录",
            },
            IntentType.CONVERSATION: {
                "response_style": "平衡、自然、专业",
                "priority": "medium",
                "actions": ["理解上下文", "延续话题"],
                "avoid": ["突兀", "生硬"],
                "prompt_hint": "普通对话模式：默认 LLM",
            },
        }
        
        return suggestions.get(
            intent_result.intent,
            suggestions[IntentType.CONVERSATION]
        )
    
    def _check_action_required(
        self, 
        intent_result: IntentResult, 
        processed: dict[str, Any]
    ) -> bool:
        """
        判断是否需要特殊行动
        
        Args:
            intent_result: 意图识别结果
            processed: 预处理结果
            
        Returns:
            是否需要特殊行动
        """
        # 高风险输入需要特别关注（危机由 guardrails_input 承接）
        if processed.get("risk_level") == "high":
            return True

        return False
    
    def build_prompt(self, user_context: dict[str, Any]) -> str:
        """
        构建大模型的prompt
        
        Args:
            user_context: 用户上下文，包含意图分析结果
            
        Returns:
            构建好的prompt字符串
        """
        # 提取意图信息
        intent_data = user_context.get("analysis", {}).get("intent", {})
        intent = intent_data.get("intent", "conversation")
        
        # 获取响应建议
        from ..models.intent_models import IntentType
        try:
            intent_type = IntentType(intent)
        except ValueError:
            intent_type = IntentType.CONVERSATION
        
        # 创建一个临时的IntentResult用于生成建议
        from ..models.intent_models import IntentResult
        intent_result = IntentResult(
            intent=intent_type,
            confidence=intent_data.get("confidence", 0.5),
            source=intent_data.get("source", "unknown")
        )
        
        suggestion = self._generate_suggestion(
            intent_result,
            {"risk_level": "low"}
        )
        
        # 构建prompt
        base_prompt = f"""
你是"NexusAI"企业信息平台助手。请根据用户的意图，给予专业、准确的回应。

【用户状态分析】
- 主要意图：{intent}
- 响应风格：{suggestion.get('response_style', '专业、清晰')}

【响应指导】
- 优先行动：{', '.join(suggestion.get('actions', [])[:3])}
- 避免：{', '.join(suggestion.get('avoid', []))}
- 提示：{suggestion.get('prompt_hint', '以用户为中心，提供准确、有用的信息')}

【基本原则】
1. 用自然、清晰的方式回应，避免说教
2. 准确理解用户需求，给出针对性解答
3. 尊重用户，提供可操作的实用建议
4. 在必要时提供可靠的信息或资源

请根据以上分析，给出专业、恰当的回应。
"""
        
        return base_prompt.strip()

