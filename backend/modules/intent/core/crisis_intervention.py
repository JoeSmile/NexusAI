#!/usr/bin/env python3
"""
安全预警模块 - 精简版（检测高风险表述并给出中性安全提示）

功能：
- 检测高风险表述（自残、轻生等）
- 触发预设的安全提示话术
- 引导用户寻求适当支持

注意：此模块已从旧项目（emotional_chat）迁移，移除热线与旧话术，
仅保留高风险检测与中性安全提示。完整的安全策略由 pipeline guardrails 统一负责。
"""

import logging

logger = logging.getLogger(__name__)


class CrisisIntervention:
    """安全预警处理器 - 核心版"""

    # 高风险关键词（核心部分）
    HIGH_RISK_KEYWORDS = [
        "不想活了", "自杀", "自残", "结束生命", "离开这个世界",
        "重度抑郁", "绝望", "没有希望", "活着没意思"
    ]

    def __init__(self, emotion_strategy: dict | None = None):
        """
        初始化安全预警处理器

        Args:
            emotion_strategy: 策略配置（可选，遗留参数）
        """
        self.emotion_strategy = emotion_strategy or {}
        logger.info("✓ 安全预警模块已初始化（精简版）")

    def is_crisis_situation(self,
                           user_emotion: str,
                           user_input: str = "",
                           metadata: dict | None = None) -> bool:
        """
        判断是否为高风险情况（核心逻辑）

        Args:
            user_emotion: 用户状态标签
            user_input: 用户输入文本
            metadata: 元数据（可能包含风险标记）

        Returns:
            是否为高风险情况
        """
        # 1. 状态类型判断
        if user_emotion == "high_risk_depression":
            return True

        # 2. 元数据标记判断
        if metadata and metadata.get("requires_crisis_intervention"):
            return True

        # 3. 高风险关键词检测
        if user_input:
            user_input_lower = user_input.lower()
            for keyword in self.HIGH_RISK_KEYWORDS:
                if keyword in user_input_lower:
                    logger.warning(f"⚠️ 检测到高风险关键词: {keyword}")
                    return True

        return False

    def generate_crisis_response(self,
                                user_input: str = "",
                                user_emotion: str = "high_risk_depression") -> str:
        """
        生成安全提示回复（核心逻辑）

        Args:
            user_input: 用户输入（可选）
            user_emotion: 用户状态

        Returns:
            安全提示回复文本
        """
        # 从策略配置获取预设回复
        crisis_strategy = self.emotion_strategy.get("high_risk_depression", {})
        fallback_response = crisis_strategy.get("fallback", "")

        if fallback_response:
            return fallback_response

        # 默认安全提示（中性）
        return (
            "我们非常关心你的安全。你现在的感受很重要，但我是企业信息平台助手，"
            "无法提供此类专业支持。\n\n"
            "建议你尽快联系身边可信赖的人，或通过公司 EAP、当地专业支持渠道寻求帮助。"
            "紧急情况下请及时拨打 120 或 110。\n\n"
            "请一定优先照顾好自己。"
        )

    def get_crisis_hotlines(self) -> list[dict[str, str]]:
        """
        获取配置中的支持渠道（旧项目热线已移除）

        Returns:
            支持渠道列表（默认空）
        """
        strategy_hotlines = self.emotion_strategy.get("high_risk_depression", {}).get("crisis_hotlines", [])
        return strategy_hotlines if strategy_hotlines else []


# 便捷函数
def check_crisis(user_emotion: str,
                user_input: str = "",
                metadata: dict | None = None) -> bool:
    """
    便捷函数：检查是否为高风险情况

    Args:
        user_emotion: 用户状态
        user_input: 用户输入
        metadata: 元数据

    Returns:
        是否为高风险情况
    """
    intervention = CrisisIntervention()
    return intervention.is_crisis_situation(user_emotion, user_input, metadata)


def get_crisis_response(user_input: str = "",
                       user_emotion: str = "high_risk_depression",
                       emotion_strategy: dict | None = None) -> str:
    """
    便捷函数：获取安全提示回复

    Args:
        user_input: 用户输入
        user_emotion: 用户状态
        emotion_strategy: 策略配置

    Returns:
        安全提示回复
    """
    intervention = CrisisIntervention(emotion_strategy)
    return intervention.generate_crisis_response(user_input, user_emotion)


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 测试用例
    test_cases = [
        {
            "user_input": "我真的不想活了",
            "user_emotion": "sad",
            "expected_crisis": True
        },
        {
            "user_input": "今天心情不太好",
            "user_emotion": "sad",
            "expected_crisis": False
        },
        {
            "user_input": "",
            "user_emotion": "high_risk_depression",
            "expected_crisis": True
        }
    ]

    print("\n===== 安全预警测试（精简版）=====\n")

    intervention = CrisisIntervention()

    for i, test in enumerate(test_cases, 1):
        is_crisis = intervention.is_crisis_situation(
            user_emotion=test["user_emotion"],
            user_input=test["user_input"]
        )

        status = "✓" if is_crisis == test["expected_crisis"] else "✗"
        print(f"{status} 测试 {i}:")
        print(f"   输入: {test['user_input'] or '(空)'}")
        print(f"   状态: {test['user_emotion']}")
        print(f"   判断: {'高风险' if is_crisis else '正常'}")

        if is_crisis:
            response = intervention.generate_crisis_response(
                test["user_input"],
                test["user_emotion"]
            )
            print(f"   回复: {response[:100]}...")
        print()
