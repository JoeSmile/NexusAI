"""内置 Skill — 情绪回应（双路径短路径示例）"""

from __future__ import annotations

from backend.skills.base import BaseSkill, SkillResult


class EmotionResponseSkill(BaseSkill):
    id = "emotion_response"
    name = "情绪回应"
    description = "对用户的情绪表达做出回应"
    trigger_intents = ["emotion"]
    required_permissions: list[str] = []

    async def _do_execute(self, entities: dict) -> SkillResult:
        emotion = entities.get("emotion", "neutral")
        # entities 可能把整句塞进 emotion 字段
        text = emotion if isinstance(emotion, str) else "neutral"
        templates = {
            "焦虑": "听起来你有些焦虑。要不要聊聊是什么让你感到不安？我在这里陪着你。",
            "悲伤": "我理解你的感受。有时候把伤心的事说出来，心里会好受一些。",
            "高兴": "真为你高兴！能分享你的快乐，我也感觉很温暖。",
            "愤怒": "你看起来有些生气。先深呼吸一下，慢慢说，我在听。",
            "孤独": "感到孤独确实很难受。你不是一个人，我随时在这里陪你聊天。",
            "害怕": "害怕是很正常的情绪。你可以告诉我发生了什么，我们一起面对。",
            "neutral": "我在听，你继续说吧。",
        }
        aliases = {"压力": "焦虑", "难过": "悲伤", "生气": "愤怒", "害怕": "害怕"}
        matched = "neutral"
        for alias, key in aliases.items():
            if alias in text:
                matched = key
                break
        if matched == "neutral":
            for key in templates:
                if key != "neutral" and key in text:
                    matched = key
                    break
        return SkillResult(output=templates[matched], latency_ms=1.0)
