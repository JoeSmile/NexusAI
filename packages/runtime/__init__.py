"""
Runtime — NexusAI Agent Runtime

从线性 Workflow 升级为 Runtime + Skills 架构：
- Protocol-first: 三协议抽象 (LLM / Tool / Permission)
- Skill-based: 每个 workflow 阶段变为独立 Skill
- FSM-governed: 会话有 6 状态 FSM
- Toggle-gated: 每个模块可独立开关
- Hook-extensible: pre/post 行为可注入
- Policy-driven: 声明式规则引擎
- Workspace-isolated: 用户/会话工作区隔离
"""

from packages.runtime.activity.distiller import ActivityDistiller, TurnDigest
from packages.runtime.activity.tracker import ActivityTracker
from packages.runtime.budget.pressure import BudgetPressure
from packages.runtime.config.guards import is_module_enabled, require_module
from packages.runtime.config.toggles import ModuleToggles
from packages.runtime.conversation import ConversationRuntime
from packages.runtime.fallback.manager import FallbackConfig, FallbackManager
from packages.runtime.hooks.base import HookContext, HookDispatcher, PluginHook
from packages.runtime.policy.policy_engine import PolicyEngine, PolicyRule
from packages.runtime.prompt_builder import PromptLayer, SystemPromptBuilder
from packages.runtime.protocols import (
    AssistantEvent,
    LLMClient,
    PermissionDecision,
    PermissionPrompter,
    PermissionRequest,
    ToolExecutor,
    ToolResult,
    TurnSummary,
)
from packages.runtime.session.fsm import IllegalTransitionError, SessionFSM, SessionState
from packages.runtime.skills.base import Skill, SkillContext, SkillRegistry, SkillResult
from packages.runtime.skills.memory_skill import MemorySkill
from packages.runtime.skills.planning_skill import PlanningSkill
from packages.runtime.skills.reflect_skill import ReflectSkill
from packages.runtime.skills.tool_skill import ToolSkill
from packages.runtime.task_packet import TaskPacket, TaskPriority, TaskStatus
from packages.runtime.workspace.manager import WorkspaceInfo, WorkspaceManager

__all__ = [
    # Protocols
    "AssistantEvent",
    "LLMClient",
    "PermissionDecision",
    "PermissionPrompter",
    "PermissionRequest",
    "ToolExecutor",
    "ToolResult",
    "TurnSummary",
    # Session
    "SessionFSM",
    "SessionState",
    "IllegalTransitionError",
    # Config
    "ModuleToggles",
    "is_module_enabled",
    "require_module",
    # Skills
    "Skill",
    "SkillContext",
    "SkillResult",
    "SkillRegistry",
    "MemorySkill",
    "PlanningSkill",
    "ReflectSkill",
    "ToolSkill",
    # Policy
    "PolicyEngine",
    "PolicyRule",
    # Hooks
    "PluginHook",
    "HookDispatcher",
    "HookContext",
    # Conversation
    "ConversationRuntime",
    # Budget
    "BudgetPressure",
    # Fallback
    "FallbackManager",
    "FallbackConfig",
    # Workspace
    "WorkspaceManager",
    "WorkspaceInfo",
    # Activity
    "ActivityTracker",
    "ActivityDistiller",
    "TurnDigest",
    # Prompt
    "SystemPromptBuilder",
    "PromptLayer",
    # Task
    "TaskPacket",
    "TaskPriority",
    "TaskStatus",
]
