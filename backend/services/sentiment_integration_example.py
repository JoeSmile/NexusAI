#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情感分析集成示例
展示如何将高级情感分析集成到现有的对话流程中
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from backend.services.advanced_sentiment_analyzer import AdvancedSentimentAnalyzer, get_analyzer
from backend.services.emotion_trend_analyzer import EmotionTrendAnalyzer
from backend.database import DatabaseManager

logger = logging.getLogger(__name__)


class SentimentIntegratedChatService:
    """
    集成情感分析的聊天服务示例
    
    展示如何在对话流程中完整集成：
    1. 实时情感分析
    2. 动态Prompt调整
    3. 情绪趋势追踪
    4. 风险预警
    """
    
    def __init__(self, use_transformers: bool = False):
        """
        初始化服务
        
        Args:
            use_transformers: 是否使用Transformers模型（默认False，避免网络问题）
        """
        # 初始化情感分析器
        self.sentiment_analyzer = AdvancedSentimentAnalyzer(use_transformers=use_transformers)
        
        # 初始化趋势分析器
        self.trend_analyzer = EmotionTrendAnalyzer()
        
        logger.info("✓ 情感分析集成服务初始化完成")
    
    def process_message_with_sentiment(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
        check_trend: bool = True
    ) -> Dict:
        """
        处理消息并进行情感分析
        
        这是完整的集成流程示例
        
        Args:
            user_message: 用户消息
            user_id: 用户ID
            session_id: 会话ID
            check_trend: 是否检查情绪趋势
        
        Returns:
            包含情感分析结果和增强Prompt的字典
        """
        try:
            # ====================
            # 步骤1：实时情感分析
            # ====================
            sentiment_result = self.sentiment_analyzer.analyze(user_message, user_id)
            
            logger.info(f"用户 {user_id} 情感分析: {sentiment_result['emotion']} "
                       f"(强度: {sentiment_result['intensity']}, "
                       f"置信度: {sentiment_result['confidence']})")
            
            # ====================
            # 步骤2：情绪趋势分析（可选）
            # ====================
            trend_result = None
            if check_trend:
                try:
                    trend_result = self.sentiment_analyzer.get_emotion_trend(user_id, window=10)
                    
                    # 检查风险预警
                    if trend_result.get('warning'):
                        logger.warning(f"⚠️ 用户 {user_id} 情绪预警: {trend_result['warning']}")
                        
                        # 这里可以触发额外的关怀机制
                        # 例如：通知人工客服、推荐专业资源等
                    
                except Exception as e:
                    logger.error(f"趋势分析失败: {e}")
            
            # ====================
            # 步骤3：构建情绪感知Prompt
            # ====================
            base_prompt = """你是一个温暖、耐心的心理健康陪伴者，名叫"ContextGate"。
你的目标是提供情感支持、倾听和陪伴，而不是直接给出建议或解决方案。
请用共情、支持性的语言回应用户。"""
            
            enhanced_prompt = self.sentiment_analyzer.build_emotion_aware_prompt(
                sentiment_result,
                base_prompt
            )
            
            logger.info(f"已生成情绪感知Prompt（长度: {len(enhanced_prompt)}字符）")
            
            # ====================
            # 步骤4：准备上下文信息
            # ====================
            context = {
                "emotion": sentiment_result["emotion"],
                "emotion_intensity": sentiment_result["intensity"],
                "emotion_confidence": sentiment_result["confidence"],
                "emotion_polarity": sentiment_result["polarity"],
                "emotion_scores": sentiment_result.get("emotion_scores", {}),
                "keywords": sentiment_result.get("keywords", []),
                "suggestions": sentiment_result.get("suggestions", []),
                "analysis_method": sentiment_result.get("method", "unknown")
            }
            
            # 添加趋势信息（如果有）
            if trend_result:
                context["emotion_trend"] = {
                    "trend": trend_result.get("trend", "unknown"),
                    "average_intensity": trend_result.get("average_intensity", 0),
                    "dominant_emotion": trend_result.get("dominant_emotion", "neutral"),
                    "warning": trend_result.get("warning")
                }
            
            # ====================
            # 步骤5：风险检测和特殊处理
            # ====================
            risk_response = self._handle_high_risk_situations(sentiment_result, trend_result)
            
            if risk_response:
                # 如果检测到高风险情况，使用特殊响应
                return {
                    "enhanced_prompt": enhanced_prompt,
                    "sentiment": sentiment_result,
                    "trend": trend_result,
                    "context": context,
                    "high_risk_detected": True,
                    "risk_response": risk_response
                }
            
            # ====================
            # 返回完整的分析结果
            # ====================
            return {
                "enhanced_prompt": enhanced_prompt,
                "sentiment": sentiment_result,
                "trend": trend_result,
                "context": context,
                "high_risk_detected": False,
                "risk_response": None
            }
            
        except Exception as e:
            logger.error(f"情感分析集成处理失败: {e}")
            
            # 返回降级结果
            return {
                "enhanced_prompt": base_prompt,
                "sentiment": {"emotion": "neutral", "intensity": 5.0},
                "trend": None,
                "context": {},
                "high_risk_detected": False,
                "risk_response": None,
                "error": str(e)
            }
    
    def _handle_high_risk_situations(
        self,
        sentiment_result: Dict,
        trend_result: Optional[Dict]
    ) -> Optional[str]:
        """
        处理高风险情况
        
        检测并响应可能的心理危机
        
        Args:
            sentiment_result: 情感分析结果
            trend_result: 趋势分析结果
        
        Returns:
            如果是高风险情况，返回特殊响应文本；否则返回None
        """
        emotion = sentiment_result.get("emotion")
        intensity = sentiment_result.get("intensity", 0)
        
        # 1. 极端负面情绪 + 高强度
        if emotion in ["sad", "anxious", "lonely"] and intensity >= 8:
            return self._generate_crisis_response(emotion)
        
        # 2. 趋势预警
        if trend_result and trend_result.get("warning") == "high_risk":
            return self._generate_crisis_response("high_risk_trend")
        
        # 3. 关键词检测（更严格的危机信号）
        crisis_keywords = ["自杀", "自残", "不想活", "结束生命", "了结"]
        user_message = sentiment_result.get("original_text", "")
        
        if any(keyword in user_message for keyword in crisis_keywords):
            return self._generate_crisis_response("crisis_keyword")
        
        return None
    
    def _generate_crisis_response(self, crisis_type: str) -> str:
        """生成危机响应"""
        responses = {
            "sad": """我非常关心你现在的状态。你现在的感受很重要，但请一定要寻求专业帮助。

建议立即联系心理援助热线：
- 希望24热线：400-161-9995（24小时）
- 北京心理危机干预中心：010-82951332
- 生命热线：400-821-1215

你不是一个人，很多人愿意帮助你。我会一直在这里陪着你。""",
            
            "anxious": """我能感受到你现在非常焦虑。这种感觉一定很难受。

如果你感到无法控制的焦虑，建议联系专业心理援助：
- 希望24热线：400-161-9995
- 也可以考虑寻找专业心理咨询师

在等待的同时，让我们尝试深呼吸：慢慢吸气（4秒）- 保持（4秒）- 慢慢呼气（4秒）。

我在这里陪着你。""",
            
            "lonely": """孤独的感觉确实很难承受。我想让你知道，你并不孤单。

如果孤独感让你感到痛苦，建议：
1. 联系心理援助热线：400-161-9995
2. 尝试线上心理咨询平台
3. 考虑加入支持小组

我会一直在这里陪着你。你的感受很重要，值得被倾听和理解。""",
            
            "high_risk_trend": """我注意到你最近的情绪状态持续低落。这让我很关心。

建议考虑寻求专业支持：
- 心理援助热线：400-161-9995（希望24热线，24小时）
- 预约专业心理咨询师

你的感受很重要，专业的帮助会对你有益。我也会继续在这里陪伴你。""",
            
            "crisis_keyword": """我非常担心你现在的状态。如果你有伤害自己的想法，请立即寻求帮助：

🚨 紧急联系方式：
- 心理危机干预热线：010-82951332
- 希望24热线：400-161-9995
- 生命热线：400-821-1215
- 或拨打120、110寻求紧急援助

你的生命很宝贵。现在的痛苦不会永远持续。请给专业人士一个帮助你的机会。

我也会一直在这里。"""
        }
        
        return responses.get(crisis_type, responses["high_risk_trend"])
    
    def get_user_emotion_report(self, user_id: str, days: int = 7) -> Dict:
        """
        生成用户情绪报告
        
        综合情感分析和趋势分析，生成完整的情绪报告
        
        Args:
            user_id: 用户ID
            days: 分析天数
        
        Returns:
            情绪报告
        """
        try:
            # 获取详细趋势分析
            trend_report = self.trend_analyzer.analyze_user_emotion_trend(
                user_id,
                days,
                include_visualization_data=True
            )
            
            # 获取多维度情绪画像
            emotion_profile = self.trend_analyzer.get_multi_dimensional_emotion_profile(
                user_id,
                days=min(days * 2, 30)  # 使用更长的时间窗口
            )
            
            # 获取实时趋势
            realtime_trend = self.sentiment_analyzer.get_emotion_trend(user_id, window=10)
            
            return {
                "user_id": user_id,
                "report_date": datetime.now().isoformat(),
                "analysis_period_days": days,
                "trend_analysis": trend_report,
                "emotion_profile": emotion_profile,
                "realtime_trend": realtime_trend,
                "summary": self._generate_report_summary(trend_report, emotion_profile)
            }
            
        except Exception as e:
            logger.error(f"生成情绪报告失败: {e}")
            return {
                "error": str(e),
                "user_id": user_id
            }
    
    def _generate_report_summary(self, trend_report: Dict, emotion_profile: Dict) -> str:
        """生成报告摘要"""
        try:
            dominant_emotion = trend_report.get("dominant_emotion", "未知")
            avg_intensity = trend_report.get("average_intensity", 0)
            risk_level = trend_report.get("risk_assessment", {}).get("level", "未知")
            trend = trend_report.get("trend", {}).get("trend", "未知")
            
            # 多维度得分
            wellbeing_score = emotion_profile.get("overall_wellbeing_score", 0) if emotion_profile else 0
            
            summary = f"""
【情绪报告摘要】

主导情绪：{dominant_emotion}
平均强度：{avg_intensity}/10
情绪趋势：{trend}
风险等级：{risk_level}
整体幸福感：{wellbeing_score:.2f}/1.0

"""
            
            # 添加关键发现
            if trend == "declining":
                summary += "⚠️ 关键发现：情绪呈下降趋势，建议增加关注。\n"
            elif trend == "improving":
                summary += "✅ 关键发现：情绪持续改善，继续保持！\n"
            
            if risk_level == "high":
                summary += "🔴 重要提示：检测到高风险信号，建议专业支持。\n"
            
            return summary
            
        except Exception as e:
            return f"摘要生成失败: {e}"


# ============================================
# 使用示例
# ============================================

def example_usage():
    """
    使用示例：展示如何在实际对话中集成情感分析
    """
    
    # 初始化服务
    service = SentimentIntegratedChatService(use_transformers=False)
    
    # 模拟用户消息
    user_message = "今天工作压力好大，感觉快撑不住了..."
    user_id = "user_12345"
    session_id = "session_67890"
    
    # 处理消息（含情感分析）
    result = service.process_message_with_sentiment(
        user_message=user_message,
        user_id=user_id,
        session_id=session_id,
        check_trend=True
    )
    
    # 打印结果
    print("=" * 60)
    print("情感分析集成示例")
    print("=" * 60)
    print(f"\n用户消息: {user_message}")
    print(f"\n检测到的情绪: {result['sentiment']['emotion']}")
    print(f"情绪强度: {result['sentiment']['intensity']}/10")
    print(f"置信度: {result['sentiment']['confidence']}")
    
    if result['trend']:
        print(f"\n情绪趋势: {result['trend']['trend']}")
        print(f"主导情绪: {result['trend']['dominant_emotion']}")
        if result['trend'].get('warning'):
            print(f"⚠️ 预警: {result['trend']['warning']}")
    
    print(f"\n是否高风险: {result['high_risk_detected']}")
    
    if result['high_risk_detected']:
        print(f"\n危机响应:\n{result['risk_response']}")
    
    print(f"\n增强Prompt (前200字符):\n{result['enhanced_prompt'][:200]}...")
    
    # 生成情绪报告
    print("\n" + "=" * 60)
    print("生成情绪报告示例")
    print("=" * 60)
    
    report = service.get_user_emotion_report(user_id, days=7)
    if "summary" in report:
        print(report["summary"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_usage()

