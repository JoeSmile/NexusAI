from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    emotion: str | None = None  # 情感标签

class ChatSession(BaseModel):
    session_id: str
    user_id: str | None = None
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    emotion_state: dict[str, Any] | None = None  # 当前情感状态

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str | None = None
    context: dict[str, Any] | None = None
    deep_thinking: bool | None = False  # 深度思考模式

class ChatResponse(BaseModel):
    response: str
    session_id: str
    emotion: str | None = None
    emotion_intensity: float | None = None
    suggestions: list[str] | None = None
    timestamp: datetime = Field(default_factory=datetime.now)
    context: dict[str, Any] | None = None
    plugin_used: str | None = None  # 使用的插件名称
    plugin_result: dict[str, Any] | None = None  # 插件调用结果

# 多模态支持
class MultimodalRequest(BaseModel):
    """多模态聊天请求"""
    text: str | None = None  # 文本消息
    session_id: str | None = None
    user_id: str | None = None
    context: dict[str, Any] | None = None
    audio_transcript: str | None = None  # 音频转录文本
    audio_features: dict[str, Any] | None = None  # 音频特征
    image_analysis: dict[str, Any] | None = None  # 图像分析结果

class MultimodalResponse(BaseModel):
    """多模态聊天响应"""
    response: str
    session_id: str
    emotion: str | None = None
    emotion_intensity: float | None = None
    suggestions: list[str] | None = None
    timestamp: datetime = Field(default_factory=datetime.now)
    context: dict[str, Any] | None = None
    audio_url: str | None = None  # 语音回复URL
    multimodal_emotion: dict[str, Any] | None = None  # 多模态情感融合结果

class EmotionAnalysis(BaseModel):
    emotion: str
    confidence: float
    intensity: float
    suggestions: list[str]

class FeedbackRequest(BaseModel):
    session_id: str
    user_id: str | None = None
    message_id: int | None = None
    feedback_type: str  # irrelevant, lack_empathy, overstepping, helpful, other
    rating: int  # 1-5
    comment: str | None = None
    user_message: str | None = None
    bot_response: str | None = None

class FeedbackResponse(BaseModel):
    feedback_id: int
    session_id: str
    feedback_type: str
    rating: int
    created_at: datetime
    message: str = "Feedback received successfully"

class FeedbackStatistics(BaseModel):
    total_count: int
    avg_rating: float
    by_type: list[dict[str, Any]]
    
class FeedbackListResponse(BaseModel):
    feedbacks: list[dict[str, Any]]
    total: int

# 评估相关模型
class EvaluationRequest(BaseModel):
    """评估请求模型"""
    session_id: str | None = None
    user_id: str | None = None
    message_id: int | None = None
    user_message: str
    bot_response: str
    user_emotion: str | None = "neutral"
    emotion_intensity: float | None = 5.0
    prompt_version: str | None = None  # 用于A/B测试

class EvaluationResponse(BaseModel):
    """评估响应模型"""
    evaluation_id: int
    empathy_score: float
    naturalness_score: float
    safety_score: float
    average_score: float
    total_score: float
    overall_comment: str
    strengths: list[str]
    weaknesses: list[str]
    improvement_suggestions: list[str]
    created_at: datetime

class BatchEvaluationRequest(BaseModel):
    """批量评估请求模型"""
    session_id: str | None = None
    limit: int | None = 10  # 最多评估多少条对话

class ComparePromptsRequest(BaseModel):
    """Prompt对比请求模型"""
    user_message: str
    responses: dict[str, str]  # prompt_name -> bot_response
    user_emotion: str | None = "neutral"
    emotion_intensity: float | None = 5.0

class HumanVerificationRequest(BaseModel):
    """人工验证请求模型"""
    evaluation_id: int
    empathy_score: int  # 1-5
    naturalness_score: int  # 1-5
    safety_score: int  # 1-5
    comment: str | None = None

class EvaluationStatistics(BaseModel):
    """评估统计模型"""
    total_count: int
    average_scores: dict[str, float]
    score_ranges: dict[str, dict[str, float]] | None = None
    
class EvaluationListResponse(BaseModel):
    """评估列表响应模型"""
    evaluations: list[dict[str, Any]]
    total: int
    statistics: dict[str, Any] | None = None

# 个性化配置相关模型
class PersonalizationConfig(BaseModel):
    """个性化配置模型"""
    user_id: str
    
    # 角色层
    role: str = "温暖倾听者"
    role_name: str = "ContextGate"
    role_background: str | None = None
    personality: str = "温暖耐心"
    core_principles: list[str] | None = None
    forbidden_behaviors: list[str] | None = None
    
    # 表达层
    tone: str = "温和"
    style: str = "简洁"
    formality: float = 0.3
    enthusiasm: float = 0.5
    empathy_level: float = 0.8
    humor_level: float = 0.3
    response_length: str = "medium"
    use_emoji: bool = False
    
    # 记忆层
    preferred_topics: list[str] | None = None
    avoided_topics: list[str] | None = None
    communication_preferences: dict[str, Any] | None = None
    
    # 高级设置
    learning_mode: bool = True
    safety_level: str = "standard"
    context_window: int = 10
    
    # 情境化角色
    situational_roles: dict[str, Any] | None = None
    active_role: str = "default"

class PersonalizationUpdateRequest(BaseModel):
    """个性化配置更新请求"""
    role: str | None = None
    role_name: str | None = None
    role_background: str | None = None
    personality: str | None = None
    core_principles: list[str] | None = None
    forbidden_behaviors: list[str] | None = None
    
    tone: str | None = None
    style: str | None = None
    formality: float | None = None
    enthusiasm: float | None = None
    empathy_level: float | None = None
    humor_level: float | None = None
    response_length: str | None = None
    use_emoji: bool | None = None
    
    preferred_topics: list[str] | None = None
    avoided_topics: list[str] | None = None
    communication_preferences: dict[str, Any] | None = None
    
    learning_mode: bool | None = None
    safety_level: str | None = None
    context_window: int | None = None
    
    situational_roles: dict[str, Any] | None = None
    active_role: str | None = None

class PersonalizationResponse(BaseModel):
    """个性化配置响应"""
    user_id: str
    config: PersonalizationConfig
    total_interactions: int
    positive_feedbacks: int
    config_version: int
    created_at: datetime
    updated_at: datetime

class RoleTemplate(BaseModel):
    """角色模板"""
    id: str
    name: str
    role: str
    personality: str
    tone: str
    style: str
    description: str
    icon: str
    background: str | None = None
    core_principles: list[str]
    sample_responses: list[str]
