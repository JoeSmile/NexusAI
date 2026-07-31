#!/usr/bin/env python3
"""
Agent模块数据模型
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentStatus(StrEnum):
    """Agent状态枚举"""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    WAITING = "waiting"
    ERROR = "error"
    COMPLETED = "completed"


class ActionType(StrEnum):
    """动作类型枚举"""
    SEND_MESSAGE = "send_message"
    CALL_TOOL = "call_tool"
    RETRIEVE_MEMORY = "retrieve_memory"
    PLAN_NEXT = "plan_next"
    WAIT_FOR_INPUT = "wait_for_input"
    END_CONVERSATION = "end_conversation"


class ToolType(StrEnum):
    """工具类型枚举"""
    CALENDAR = "calendar"
    REMINDER = "reminder"
    KNOWLEDGE_SEARCH = "knowledge_search"
    EMOTION_ANALYSIS = "emotion_analysis"
    MEMORY_RETRIEVAL = "memory_retrieval"
    EXTERNAL_API = "external_api"


class AgentRequest(BaseModel):
    """Agent请求模型"""
    user_message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    user_id: str = Field(..., description="用户ID")
    session_id: str = Field(..., description="会话ID")
    context: dict[str, Any] | None = Field(None, description="上下文信息")
    user_emotion: str | None = Field(None, description="用户情绪")
    available_tools: list[str] | None = Field(None, description="可用工具列表")
    max_actions: int = Field(10, ge=1, le=50, description="最大动作数量")

    @field_validator('user_message')
    @classmethod
    def validate_user_message(cls, v):
        """验证并清理用户消息"""
        if not v or not v.strip():
            raise ValueError('用户消息不能为空')
        return v.strip()


class AgentResponse(BaseModel):
    """Agent响应模型"""
    response: str = Field(..., description="Agent回复")
    actions: list['AgentAction'] = Field(..., description="执行的动作列表")
    status: AgentStatus = Field(..., description="Agent状态")
    plan: Optional['AgentPlan'] = Field(None, description="执行计划")
    reasoning: str | None = Field(None, description="推理过程")
    confidence: float = Field(..., ge=0, le=1, description="执行置信度")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间")
    metadata: dict[str, Any] | None = Field(None, description="元数据")


class AgentAction(BaseModel):
    """Agent动作模型"""
    action_id: str = Field(..., description="动作ID")
    action_type: ActionType = Field(..., description="动作类型")
    tool_name: str | None = Field(None, description="工具名称")
    parameters: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    result: Any | None = Field(None, description="执行结果")
    success: bool = Field(True, description="是否成功")
    error_message: str | None = Field(None, description="错误信息")
    execution_time: float | None = Field(None, description="执行时间")
    timestamp: datetime = Field(default_factory=datetime.now, description="执行时间")


class AgentPlan(BaseModel):
    """Agent计划模型"""
    plan_id: str = Field(..., description="计划ID")
    goal: str = Field(..., description="计划目标")
    steps: list[dict[str, Any]] = Field(..., description="计划步骤")
    priority: int = Field(1, ge=1, le=10, description="优先级")
    estimated_time: float | None = Field(None, description="预计执行时间")
    dependencies: list[str] | None = Field(None, description="依赖关系")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class AgentMemory(BaseModel):
    """Agent记忆模型"""
    memory_id: str = Field(..., description="记忆ID")
    content: str = Field(..., description="记忆内容")
    memory_type: str = Field(..., description="记忆类型")
    importance: float = Field(..., ge=0, le=1, description="重要性")
    context: dict[str, Any] | None = Field(None, description="记忆上下文")
    tags: list[str] | None = Field(None, description="记忆标签")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    last_accessed: datetime | None = Field(None, description="最后访问时间")


class AgentTool(BaseModel):
    """Agent工具模型"""
    tool_name: str = Field(..., description="工具名称")
    tool_type: ToolType = Field(..., description="工具类型")
    description: str = Field(..., description="工具描述")
    parameters_schema: dict[str, Any] = Field(..., description="参数模式")
    required_parameters: list[str] = Field(default_factory=list, description="必需参数")
    optional_parameters: list[str] = Field(default_factory=list, description="可选参数")
    enabled: bool = Field(True, description="是否启用")
    priority: int = Field(5, ge=1, le=10, description="工具优先级")
    max_execution_time: float | None = Field(None, description="最大执行时间")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tool_name": "calendar_check",
                "tool_type": "calendar",
                "description": "检查用户日程安排",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "time_range": {"type": "string"}
                    },
                    "required": ["date"]
                },
                "required_parameters": ["date"],
                "optional_parameters": ["time_range"],
                "enabled": True,
                "priority": 5
            }
        }
    )


class AgentConfig(BaseModel):
    """Agent配置模型"""
    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent名称")
    description: str = Field(..., description="Agent描述")
    personality: str | None = Field(None, description="Agent个性")
    capabilities: list[str] = Field(default_factory=list, description="能力列表")
    tools: list[str] = Field(default_factory=list, description="可用工具")
    max_iterations: int = Field(10, ge=1, le=100, description="最大迭代次数")
    timeout: float | None = Field(None, description="超时时间")
    auto_planning: bool = Field(True, description="是否自动规划")
    memory_enabled: bool = Field(True, description="是否启用记忆")
    learning_enabled: bool = Field(False, description="是否启用学习")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class AgentStats(BaseModel):
    """Agent统计信息"""
    agent_id: str = Field(..., description="Agent ID")
    total_conversations: int = Field(0, description="总会话数")
    total_actions: int = Field(0, description="总动作数")
    successful_actions: int = Field(0, description="成功动作数")
    average_response_time: float = Field(0.0, description="平均响应时间")
    tool_usage_stats: dict[str, int] = Field(default_factory=dict, description="工具使用统计")
    last_active: datetime | None = Field(None, description="最后活跃时间")


AgentResponse.model_rebuild()
