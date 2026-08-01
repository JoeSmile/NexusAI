"""
意图识别数据模型
Intent Recognition Data Models
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IntentType(StrEnum):
    """用户意图类型枚举"""

    KNOWLEDGE_QUERY = "knowledge_query"  # 企业知识库 / 制度查询
    ADVICE = "advice"  # 操作建议（中性，非情感倾诉）
    CONVERSATION = "conversation"  # 普通对话
    FUNCTION = "function"  # 功能请求（提醒、记录）
    CRISIS = "crisis"  # 危机检测（遗留意图）
    CHAT = "chat"  # 闲聊（打招呼、寒暄）


class IntentResult(BaseModel):
    """意图识别结果"""

    intent: IntentType = Field(..., description="识别的意图类型")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度（0-1）")
    source: str = Field(..., description="识别来源：rule（规则）或 model（模型）")
    secondary_intents: dict[IntentType, float] | None = Field(
        default=None,
        description="次要意图及其置信度",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="额外的元数据信息",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "intent": "knowledge_query",
                "confidence": 0.92,
                "source": "rule",
                "secondary_intents": {},
                "metadata": {
                    "keywords": ["查询", "制度"]
                },
            }
        }
    )


class IntentRequest(BaseModel):
    """意图识别请求"""

    text: str = Field(..., min_length=1, description="待识别的文本")
    user_id: str | None = Field(default=None, description="用户ID")
    session_id: str | None = Field(default=None, description="会话ID")
    context: dict[str, Any] | None = Field(
        default=None,
        description="上下文信息",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "如何查询公司的信息安全管理制度？",
                "user_id": "user_123",
                "session_id": "session_456",
            }
        }
    )
