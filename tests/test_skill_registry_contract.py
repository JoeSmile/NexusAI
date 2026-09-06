import pytest

from packages.skills.base import BaseSkill, SkillResult
from packages.skills.registry import SKILL_REGISTRY, SkillRegistry
from packages.skills.types import SkillType


def test_registry_is_explicit_mapping() -> None:
    assert "greeting" in SKILL_REGISTRY
    assert "refund_policy" in SKILL_REGISTRY
    assert not hasattr(SkillRegistry, "discover") or SkillRegistry.discover is SkillRegistry.load


def test_every_skill_declares_governance_fields() -> None:
    required = (
        "id",
        "name",
        "description",
        "skill_type",
        "skill_version",
        "enabled",
        "short_path",
        "trigger_intents",
        "required_permissions",
        "tool_whitelist",
    )
    for sid, skill in SKILL_REGISTRY.items():
        for attr in required:
            assert hasattr(skill, attr), f"{sid}.{attr}"
        assert skill.id == sid
        assert skill.skill_type in SkillType
        assert skill.skill_version  # 非空 semver 字符串


def test_short_path_only_greeting_and_after_sales() -> None:
    short = [s for s in SKILL_REGISTRY.values() if s.short_path]
    intents = {i for s in short for i in s.trigger_intents}
    assert intents <= {"greeting", "after_sales"}
    assert {s.id for s in short} == {
        "greeting",
        "refund_policy",
        "complaint_escalation",
    }


def test_disabled_skill_not_routable() -> None:
    reg = SkillRegistry()
    reg.load()
    target = reg.get_skill("quote_proposal")
    assert target is not None
    original = target.enabled
    try:
        target.enabled = False
        ids = {s.id for s in reg.list_routable("t1")}
        assert "quote_proposal" not in ids
    finally:
        target.enabled = original


def test_workflow_type_requires_executable_carrier() -> None:
    """规则 16：必须 WorkflowIR.model_validate；仅 nodes 为 list 不够。"""

    class FakeWorkflow(BaseSkill):
        id = "fake_wf"
        skill_type = SkillType.WORKFLOW

        async def _do_execute(
            self,
            entities: dict,
            *,
            tenant_id: str = "",
            user_context: dict | None = None,
        ) -> SkillResult:
            return SkillResult(output="")

    reg = SkillRegistry()
    with pytest.raises(ValueError):
        reg._assert_executable(FakeWorkflow())

    bare_list = FakeWorkflow()
    bare_list.workflow_ir = {"nodes": [{"node_id": "n1"}]}  # 缺 kind/capability_id
    with pytest.raises(ValueError):
        reg._assert_executable(bare_list)

    empty_nodes = FakeWorkflow()
    empty_nodes.workflow_ir = {
        "ir_schema": "1",
        "nodes": [],
        "edges": [],
        "inputs": {},
    }
    with pytest.raises(ValueError, match="nodes"):
        reg._assert_executable(empty_nodes)

    uuid_only = FakeWorkflow()
    uuid_only.workflow_asset_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    with pytest.raises(ValueError, match="禁止 UUID"):
        reg._assert_executable(uuid_only)

    ok = FakeWorkflow()
    ok.workflow_ir = {
        "ir_schema": "1",
        "nodes": [
            {
                "node_id": "n1",
                "kind": "capability",
                "capability_id": "llm.generate",
            }
        ],
        "edges": [],
        "inputs": {
            "topic": {"name": "topic", "type": "string", "required": False},
        },
    }
    reg._assert_executable(ok)  # 不抛


@pytest.mark.asyncio
async def test_execute_rejects_disabled() -> None:
    skill = SKILL_REGISTRY["greeting"]
    prev = skill.enabled
    skill.enabled = False
    try:
        result = await skill.execute(entities={}, tenant_id="t1", user_context={})
        assert result.success is False
        assert result.error == "SKILL_DISABLED"
    finally:
        skill.enabled = prev


@pytest.mark.asyncio
async def test_execute_rejects_tenant_mismatch() -> None:
    skill = SKILL_REGISTRY["greeting"]
    prev = skill.tenant_allowlist
    skill.tenant_allowlist = ["other-tenant"]
    try:
        result = await skill.execute(entities={}, tenant_id="t1", user_context={})
        assert result.success is False
        assert result.error == "SKILL_TENANT"
    finally:
        skill.tenant_allowlist = prev


def test_resolve_ignores_non_short_path() -> None:
    from packages.pipeline.intent_path import resolve_short_path_skill
    from packages.pipeline.state import make_initial_state
    from packages.skills.registry import registry

    registry.load()
    state = make_initial_state("t1", "u1", "s1", "写个小红书口播")
    state["intent"] = "content_creation"
    state["intent_confidence"] = 0.99
    assert resolve_short_path_skill(state) is None


def test_resolve_ignores_disabled_short_path_skill() -> None:
    from packages.pipeline.intent_path import resolve_short_path_skill
    from packages.pipeline.state import make_initial_state
    from packages.skills.registry import registry

    registry.load()
    skill = SKILL_REGISTRY["greeting"]
    prev = skill.enabled
    skill.enabled = False
    try:
        state = make_initial_state("t1", "u1", "s1", "你好")
        state["intent"] = "greeting"
        state["intent_confidence"] = 0.99
        assert resolve_short_path_skill(state) is None
    finally:
        skill.enabled = prev
