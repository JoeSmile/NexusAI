"""Agent 包：仅保留 protocol（MCP）。

Agent 运行时实现见 ``backend.agent``（经 ``backend.services.agent_service`` /
``backend.routers.agent`` 挂载为 ``/agent/*``）。本包不再导出 AgentCore /
AgentService / 路由副本（Task 31 已删除孤儿树）。
"""

from backend.modules.agent.protocol import (
    MCPContext,
    MCPLogger,
    MCPMessage,
    MCPMessageType,
    MCPProtocol,
    MCPToolCall,
    MCPToolResponse,
    create_mcp_protocol_with_context,
    get_mcp_logger,
)

__all__ = [
    "MCPContext",
    "MCPLogger",
    "MCPMessage",
    "MCPMessageType",
    "MCPProtocol",
    "MCPToolCall",
    "MCPToolResponse",
    "create_mcp_protocol_with_context",
    "get_mcp_logger",
]
