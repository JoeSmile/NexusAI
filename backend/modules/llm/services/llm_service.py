#!/usr/bin/env python3
"""
LLM服务层
统一的大语言模型调用服务
"""

import time
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from backend.core.exceptions import ExternalServiceError

from ..core.llm_core import LLMCore
from ..models.llm_models import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    LLMConfig,
    LLMProvider,
    LLMRequest,
    LLMResponse,
)


class LLMService:
    """LLM服务 - 统一的大语言模型调用接口"""
    
    def __init__(self, config: LLMConfig | None = None):
        """
        初始化LLM服务
        
        Args:
            config: LLM配置
        """
        self.config = config or LLMConfig(
            api_key="",
            provider=LLMProvider.OPENAI
        )
        self.llm_core = LLMCore(self.config)
        
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs
    ) -> LLMResponse:
        """
        聊天补全
        
        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大令牌数
            **kwargs: 其他参数
            
        Returns:
            LLM响应
        """
        start_time = time.time()
        
        try:
            # 构建请求
            request = LLMRequest(
                messages=messages,
                model=model or self.config.default_model,
                temperature=temperature or self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
                provider=self.config.provider,
                **kwargs
            )
            
            # 调用LLM核心
            response = await self.llm_core.chat_completion(request)
            
            # 计算响应时间
            response_time = time.time() - start_time
            response.response_time = response_time
            
            return response
            
        except Exception as e:
            raise ExternalServiceError(
                message=f"LLM聊天补全失败: {e!s}",
                service_name="LLM",
                status_code=500
            )
    
    async def text_completion(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs
    ) -> CompletionResponse:
        """
        文本补全
        
        Args:
            prompt: 提示文本
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大令牌数
            **kwargs: 其他参数
            
        Returns:
            补全响应
        """
        start_time = time.time()
        
        try:
            # 构建请求
            request = CompletionRequest(
                prompt=prompt,
                model=model or self.config.default_model,
                temperature=temperature or self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
                provider=self.config.provider,
                **kwargs
            )
            
            # 调用LLM核心
            response = await self.llm_core.text_completion(request)
            
            # 计算响应时间
            response_time = time.time() - start_time
            response.response_time = response_time
            
            return response
            
        except Exception as e:
            raise ExternalServiceError(
                message=f"LLM文本补全失败: {e!s}",
                service_name="LLM",
                status_code=500
            )
    
    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天补全
        
        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大令牌数
            **kwargs: 其他参数
            
        Yields:
            流式响应文本
        """
        try:
            # 构建请求
            request = LLMRequest(
                messages=messages,
                model=model or self.config.default_model,
                temperature=temperature or self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
                provider=self.config.provider,
                stream=True,
                **kwargs
            )
            
            # 流式调用
            async for chunk in self.llm_core.stream_chat_completion(request):
                yield chunk
                
        except Exception as e:
            raise ExternalServiceError(
                message=f"LLM流式聊天补全失败: {e!s}",
                service_name="LLM",
                status_code=500
            )
    

    async def extract_memories(self, text: str) -> list[dict[str, Any]]:
        """
        从文本中提取记忆
        
        Args:
            text: 输入文本
            
        Returns:
            提取的记忆列表
        """
        try:
            prompt = f"""
请从以下文本中提取重要的记忆信息，返回JSON格式的结果：

文本：{text}

请返回以下格式的JSON数组：
[
    {{
        "content": "记忆内容",
        "type": "记忆类型（如：personal, factual, preference）",
        "importance": 重要性评分（0-1的数字）,
        "keywords": ["关键词1", "关键词2"],
            }}
]

只提取真正重要和有价值的记忆，不要提取过于琐碎的信息。
"""
            
            messages = [
                ChatMessage(role="user", content=prompt)
            ]
            
            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=800
            )
            
            # 解析响应
            import json
            try:
                memories = json.loads(response.content)
                if not isinstance(memories, list):
                    memories = [memories]
                return memories
            except json.JSONDecodeError:
                return []
                
        except Exception as e:
            raise ExternalServiceError(
                message=f"记忆提取失败: {e!s}",
                service_name="LLM",
                status_code=500
            )
    
    async def generate_response(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
        personality: str = "专业、严谨、清晰",
        **kwargs
    ) -> str:
        """
        生成回复
        
        Args:
            user_message: 用户消息
            context: 上下文信息
            personality: 机器人个性
            **kwargs: 其他参数
            
        Returns:
            生成的回复
        """
        try:
            # 构建系统提示
            system_prompt = f"""你是"ContextGate"，一个专业的心理健康陪伴机器人。

个性特点：{personality}

你的职责：
1. 倾听用户的心声，给予温暖的支持
2. 提供专业的心理健康建议
4. 鼓励用户积极面对生活

回复要求：
- 用专业、清晰的语气
- 提供具体可操作的建议
- 避免给出医疗诊断
- 鼓励用户寻求专业帮助（如需要）
- 保持回复简洁明了（200字以内）
"""

            # 添加上下文信息
            if context:
                context_info = []
                if context.get("memories"):
                    context_info.append(f"相关记忆：{context['memories']}")
                if context.get("user_profile"):
                    context_info.append(f"用户画像：{context['user_profile']}")
                
                if context_info:
                    system_prompt += "\n\n当前上下文：\n" + "\n".join(context_info)

            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message)
            ]
            
            response = await self.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=500,
                **kwargs
            )
            
            return response.content
            
        except Exception as e:
            raise ExternalServiceError(
                message=f"回复生成失败: {e!s}",
                service_name="LLM",
                status_code=500
            )
    
    async def health_check(self) -> dict[str, Any]:
        """
        健康检查
        
        Returns:
            健康状态信息
        """
        try:
            # 发送简单测试请求
            messages = [
                ChatMessage(role="user", content="Hello")
            ]
            
            start_time = time.time()
            await self.chat_completion(
                messages=messages,
                max_tokens=10,
                temperature=0.1
            )
            response_time = time.time() - start_time
            
            return {
                "status": "healthy",
                "provider": self.config.provider.value,
                "model": self.config.default_model,
                "response_time": response_time,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "provider": self.config.provider.value,
                "timestamp": datetime.now().isoformat()
            }
