"""Regression tests for memory tenant isolation and vector ownership."""

from unittest.mock import MagicMock, patch

from backend.agent.memory_hub import get_memory_hub, reset_memory_hub
from backend.memory_manager import MemoryManager


def make_manager(tenant_id: str = "default"):
    manager = MemoryManager.__new__(MemoryManager)
    manager.memory_collection = True
    manager.tenant_id = tenant_id
    return manager


def test_memory_hub_is_isolated_by_user_and_session():
    reset_memory_hub()

    alice_first = get_memory_hub("alice", "session-1")
    alice_again = get_memory_hub("alice", "session-1")
    alice_other_session = get_memory_hub("alice", "session-2")
    bob = get_memory_hub("bob", "session-1")

    assert alice_first is alice_again
    assert alice_first is not alice_other_session
    assert alice_first is not bob
    assert alice_first.user_store.store_id == "user_alice"
    assert bob.user_store.store_id == "user_bob"


def test_reset_memory_hub_can_target_one_user():
    reset_memory_hub()
    alice = get_memory_hub("alice", "session-1")
    bob = get_memory_hub("bob", "session-1")

    reset_memory_hub(user_id="alice")

    assert get_memory_hub("alice", "session-1") is not alice
    assert get_memory_hub("bob", "session-1") is bob


def test_vector_delete_rejects_wrong_owner():
    manager = make_manager()
    row = MagicMock()
    row.user_id = "alice"
    row.tenant_id = "default"

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = row
    sf = MagicMock()
    sf.Session.return_value.__enter__.return_value = session
    sf.Session.return_value.__exit__.return_value = False

    with patch("backend.database.pgvector_session.get_pg_session", return_value=sf):
        assert manager.delete_memory("bob", "1") is False
    session.delete.assert_not_called()


def test_vector_delete_allows_owner():
    manager = make_manager()
    row = MagicMock()
    row.user_id = "alice"
    row.tenant_id = "default"

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = row
    sf = MagicMock()
    sf.Session.return_value.__enter__.return_value = session
    sf.Session.return_value.__exit__.return_value = False

    with patch("backend.database.pgvector_session.get_pg_session", return_value=sf):
        assert manager.delete_memory("alice", "1") is True
    session.delete.assert_called_once_with(row)
    session.commit.assert_called_once()


def test_importance_update_changes_vector_metadata():
    manager = make_manager()
    row = MagicMock()
    row.confidence = 0.4

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = row
    sf = MagicMock()
    sf.Session.return_value.__enter__.return_value = session
    sf.Session.return_value.__exit__.return_value = False

    with patch("backend.database.pgvector_session.get_pg_session", return_value=sf):
        assert manager.update_memory_importance("1", 0.9) is True
    assert row.confidence == 0.9
    session.commit.assert_called_once()
