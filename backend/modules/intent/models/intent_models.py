"""
意图识别数据模型
Intent Recognition Data Models
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

INTENT_TIER_HIGH = 0.85
INTENT_TIER_LOW = 0.4


def confidence_tier(confidence: float) -> str:
    """三档置信度路由（Task 65 slice 9）。"""
    if confidence >= INTENT_TIER_HIGH:
        return "high"
    if confidence >= INTENT_TIER_LOW:
        return "low"
    return "fallback"


class IntentType(StrEnum):
    """用户意图类型枚举（Task 65 切片 8 · 8 类业务导向 L0）"""

    GREETING = "greeting"
    PRE_SALES = "pre_sales"
    AFTER_SALES = "after_sales"
    CONTENT_CREATION = "content_creation"
    CONTENT_ANALYSIS = "content_analysis"
    KNOWLEDGE_QUERY = "knowledge_query"
    FUNCTION = "function"
    CONVERSATION = "conversation"


class IntentResult(BaseModel):
    """意图识别结果"""

    intent: IntentType = Field(..., description="识别的意图类型")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度（0-1）")
    source: str = Field(..., description="识别来源：rule（规则）或 model（模型）")
    tier: str | None = Field(
        default=None,
        description="置信度档位：high|low|fallback",
    )
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
