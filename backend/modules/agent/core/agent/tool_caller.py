"""
Tool Caller - 工具调用模块

负责：
- 工具注册与管理
- 工具调用执行
- 参数验证
- 结果解析

支持MCP协议：接收MCP工具请求，返回标准化的MCP工具响应
"""

import inspect
import json
import os

# 导入MCP协议
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, project_root)

from backend.modules.agent.protocol.mcp import (
    MCPMessage,
    MCPProtocol,
    MCPToolResponse,
    get_mcp_logger,
)


class Tool:
    """工具定义"""
    
    def __init__(
        self,
        name: str,
        description: str,
        function: Callable,
        parameters: dict[str, Any],
        category: str = "general"
    ):
        self.name = name
        self.description = description
        self.function = function
        self.parameters = parameters
        self.category = category
        self.created_at = datetime.now()
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category
        }


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.tools: dict[str, Tool] = {}
    
    def register(
        self,
        name: str,
        description: str,
        function: Callable,
        parameters: dict[str, Any],
        category: str = "general"
    ):
        """注册工具"""
        tool = Tool(name, description, function, parameters, category)
        self.tools[name] = tool
    
    def get_tool(self, name: str) -> Tool | None:
        """获取工具"""
        return self.tools.get(name)
    
    def list_tools(self, category: str | None = None) -> list[Tool]:
        """列出所有工具"""
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())
    
    def get_available_tools(self) -> list[str]:
        """获取可用工具名称列表"""
        return list(self.tools.keys())


class ToolCaller:
    """工具调用模块 - Agent的工具接口"""
    
    def __init__(self):
        self.registry = ToolRegistry()
        self._register_builtin_tools()
        
        # 调用历史
        self.call_history: list[dict[str, Any]] = []
        
        # MCP协议支持
        self.mcp_protocol = MCPProtocol()
        self.mcp_logger = get_mcp_logger()
    
    def _register_builtin_tools(self):
        """注册内置工具"""
        
        # ========== 记忆相关工具 ==========
        
        self.registry.register(
            name="search_memory",
            description="搜索用户历史记忆和对话",
            function=self._search_memory,
            parameters={
                "query": {"type": "string", "required": True, "description": "搜索关键词"},
                "user_id": {"type": "string", "required": True, "description": "用户ID"},
                "time_range": {"type": "int", "required": False, "default": 30, "description": "时间范围（天）"}
            },
            category="memory"
        )
        
        # ========== 定时任务工具 ==========
        
        self.registry.register(
            name="set_reminder",
            description="设置定时提醒任务",
            function=self._set_reminder,
            parameters={
                "content": {"type": "string", "required": True, "description": "提醒内容"},
                "user_id": {"type": "string", "required": True, "description": "用户ID"},
                "schedule_time": {"type": "string", "required": True, "description": "提醒时间（ISO格式）"},
                "repeat": {"type": "bool", "required": False, "default": False, "description": "是否重复"}
            },
            category="scheduler"
        )
        
        # ========== 日历工具 ==========
        
        self.registry.register(
            name="check_calendar",
            description="查看用户日历事件",
            function=self._check_calendar,
            parameters={
                "user_id": {"type": "string", "required": True, "description": "用户ID"},
                "start_date": {"type": "string", "required": False, "description": "开始日期"},
                "end_date": {"type": "string", "required": False, "description": "结束日期"}
            },
            category="calendar"
        )
    
    async def call(
        self, 
        tool_name: str, 
        parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            parameters: 调用参数
            
        Returns:
            工具执行结果
        """
        call_record = {
            "tool": tool_name,
            "parameters": parameters,
            "timestamp": datetime.now(),
            "success": False
        }
        
        try:
            # 获取工具
            tool = self.registry.get_tool(tool_name)
            
            if not tool:
                raise ValueError(f"工具不存在: {tool_name}")
            
            # 验证参数
            self._validate_parameters(tool, parameters)
            
            # 执行调用
            if inspect.iscoroutinefunction(tool.function):
                result = await tool.function(**parameters)
            else:
                result = tool.function(**parameters)
            
            call_record["success"] = True
            call_record["result"] = result
            
            # 记录调用历史
            self.call_history.append(call_record)
            
            return {
                "success": True,
                "tool": tool_name,
                "result": result,
                "timestamp": call_record["timestamp"].isoformat()
            }
            
        except Exception as e:
            call_record["error"] = str(e)
            self.call_history.append(call_record)
            
            return {
                "success": False,
                "tool": tool_name,
                "error": str(e),
                "timestamp": call_record["timestamp"].isoformat()
            }
    
    async def call_with_mcp(
        self,
        mcp_message: MCPMessage
    ) -> MCPMessage:
        """
        使用MCP协议执行工具调用（新接口）
        
        Args:
            mcp_message: 输入的MCP消息（包含tool_calls）
            
        Returns:
            输出的MCP消息（包含tool_responses）
        """
        import time
        
        tool_responses = []
        
        # 执行所有工具调用
        for tool_call in mcp_message.tool_calls:
            start_time = time.time()
            
            try:
                # 调用工具
                result = await self.call(tool_call.tool_name, tool_call.parameters)
                execution_time = time.time() - start_time
                
                # 创建工具响应
                tool_response = MCPToolResponse(
                    tool_id=tool_call.tool_id,
                    tool_name=tool_call.tool_name,
                    success=result.get("success", False),
                    result=result.get("result"),
                    error=result.get("error"),
                    execution_time=execution_time
                )
                tool_responses.append(tool_response)
                
            except Exception as e:
                execution_time = time.time() - start_time
                tool_response = MCPToolResponse(
                    tool_id=tool_call.tool_id,
                    tool_name=tool_call.tool_name,
                    success=False,
                    error=str(e),
                    execution_time=execution_time
                )
                tool_responses.append(tool_response)
        
        # 创建MCP响应消息
        output_message = self.mcp_protocol.create_tool_response(
            tool_responses=tool_responses,
            context=mcp_message.context
        )
        
        # 设置元数据
        output_message.metadata = {
            **(output_message.metadata or {}),
            "interaction_id": mcp_message.metadata.get("interaction_id") if mcp_message.metadata else None,
            "source_message_id": mcp_message.message_id
        }
        
        # 记录日志
        self.mcp_logger.log(output_message)
        
        return output_message
    
    def _validate_parameters(self, tool: Tool, parameters: dict[str, Any]):
        """
        验证工具参数
        
        检查必需参数是否存在，类型是否正确
        """
        for param_name, param_spec in tool.parameters.items():
            # 检查必需参数
            if param_spec.get("required", False):
                if param_name not in parameters:
                    raise ValueError(f"缺少必需参数: {param_name}")
            
            # 如果参数存在，检查类型
            if param_name in parameters:
                expected_type = param_spec.get("type")
                actual_value = parameters[param_name]
                
                # 简单类型检查
                type_map = {
                    "string": str,
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "list": list,
                    "dict": dict
                }
                
                if expected_type in type_map:
                    expected_python_type = type_map[expected_type]
                    if not isinstance(actual_value, expected_python_type):
                        raise TypeError(
                            f"参数 {param_name} 类型错误: "
                            f"期望 {expected_type}, 实际 {type(actual_value).__name__}"
                        )
    
    def get_call_history(
        self, 
        limit: int = 10, 
        tool_name: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取调用历史
        
        Args:
            limit: 返回数量限制
            tool_name: 过滤特定工具（可选）
            
        Returns:
            调用历史列表
        """
        history = self.call_history
        
        if tool_name:
            history = [h for h in history if h["tool"] == tool_name]
        
        return history[-limit:]
    
    # ==================== 工具实现 ====================
    
    async def _search_memory(
        self,
        query: str,
        user_id: str,
        time_range: int = 30
    ) -> dict[str, Any]:
        """搜索记忆工具实现"""
        try:
            from .memory_hub import get_memory_hub
            
            memory_hub = get_memory_hub()
            
            context = {"time_range": time_range}
            
            results = memory_hub.retrieve(
                query=query,
                user_id=user_id,
                context=context,
                top_k=5
            )
            
            return {
                "count": len(results),
                "memories": [
                    {
                        "content": m.get("content", ""),
                        "timestamp": m.get("timestamp", "").isoformat() if hasattr(m.get("timestamp", ""), "isoformat") else str(m.get("timestamp", "")),
                        "importance": m.get("importance", 0)
                    }
                    for m in results
                ]
            }
        
        except Exception as e:
            return {
                "count": 0,
                "memories": [],
                "error": str(e)
            }
    

    async def _set_reminder(
        self,
        content: str,
        user_id: str,
        schedule_time: str,
        repeat: bool = False
    ) -> dict[str, Any]:
        """设置提醒工具实现"""
        try:
            # 这里应该集成实际的定时任务系统（APScheduler等）
            # 简化实现：只是返回提醒信息
            
            return {
                "reminder_id": f"reminder_{datetime.now().timestamp()}",
                "user_id": user_id,
                "content": content,
                "scheduled_at": schedule_time,
                "repeat": repeat,
                "status": "scheduled",
                "message": f"已设置提醒：{content}"
            }
        
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    



    async def _check_calendar(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None
    ) -> dict[str, Any]:
        """查看日历事件"""
        # 简化实现：返回模拟数据
        # 实际应该对接用户日历API
        
        return {
            "user_id": user_id,
            "events": [
                {
                    "title": "重要会议",
                    "date": "2025-10-16",
                    "time": "14:00",
                    "type": "work"
                },
                {
                    "title": "健身",
                    "date": "2025-10-17",
                    "time": "18:00",
                    "type": "personal"
                }
            ],
            "count": 2,
            "message": "查询到2个即将到来的事件"
        }


# 单例模式
_tool_caller_instance = None

def get_tool_caller() -> ToolCaller:
    """获取全局ToolCaller实例"""
    global _tool_caller_instance
    if _tool_caller_instance is None:
        _tool_caller_instance = ToolCaller()
    return _tool_caller_instance


# 使用示例
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # 创建工具调用器
        tool_caller = ToolCaller()
        
        # 列出所有工具
        print("可用工具：")
        for tool in tool_caller.registry.list_tools():
            print(f"  - {tool.name}: {tool.description}")
        
        print("\n" + "="*50 + "\n")
        
        # 调用工具示例1：搜索记忆
        print("1. 搜索记忆：")
        result = await tool_caller.call(
            "search_memory",
            {
                "query": "API网关",
                "user_id": "user_123",
                "time_range": 7
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        print("\n" + "="*50 + "\n")
        
        # 调用工具示例2：查询项目知识
        print("2. 查询项目知识：")
        result = await tool_caller.call(
            "search_memory",
            {
                "query": "项目部署",
                "user_id": "user_123",
                "time_range": 30
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        print("\n" + "="*50 + "\n")
        
        # 调用工具示例3：设置提醒
        print("3. 设置提醒：")
        result = await tool_caller.call(
            "set_reminder",
            {
                "content": "下午三点项目评审会议",
                "user_id": "user_123",
                "schedule_time": "2025-10-15T15:00:00",
                "repeat": False
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    asyncio.run(main())

