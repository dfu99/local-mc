"""Round-trip tests for lmc/store.py."""
from __future__ import annotations

import time

import pytest

from lmc.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(db_path=tmp_path / "test.db")


# ── sessions ──────────────────────────────────────────────────────────────


def test_create_session(store):
    s = store.create_session("proj1")
    assert s.id
    assert s.project == "proj1"
    assert s.claude_session_id is None
    assert s.created_at > 0


def test_get_session(store):
    s = store.create_session("proj1")
    got = store.get_session(s.id)
    assert got is not None
    assert got.id == s.id
    assert got.project == "proj1"


def test_get_session_missing(store):
    assert store.get_session("nonexistent") is None


def test_list_sessions(store):
    store.create_session("proj1")
    store.create_session("proj1")
    store.create_session("proj2")
    sessions = store.list_sessions("proj1")
    assert len(sessions) == 2
    assert all(s.project == "proj1" for s in sessions)


def test_list_sessions_all(store):
    store.create_session("proj1")
    store.create_session("proj2")
    all_sessions = store.list_sessions()
    assert len(all_sessions) == 2


def test_list_sessions_empty(store):
    assert store.list_sessions("ghost") == []


def test_update_session_claude_id(store):
    s = store.create_session("p")
    store.update_session(s.id, claude_session_id="claude-abc")
    got = store.get_session(s.id)
    assert got.claude_session_id == "claude-abc"


def test_update_session_bumps_activity(store):
    s = store.create_session("p")
    t0 = s.last_active_at
    time.sleep(0.01)
    store.update_session(s.id, bump_activity=True)
    got = store.get_session(s.id)
    assert got.last_active_at >= t0


def test_delete_session(store):
    s = store.create_session("p")
    store.delete_session(s.id)
    assert store.get_session(s.id) is None


def test_delete_session_cascades_messages(store):
    s = store.create_session("p")
    store.add_message(s.id, "user", "hello")
    store.delete_session(s.id)
    # After delete, messages query should return nothing (FK cascade).
    assert store.messages(s.id) == []


def test_latest_session(store):
    s1 = store.create_session("p")
    time.sleep(0.01)
    s2 = store.create_session("p")
    latest = store.latest_session("p")
    assert latest is not None
    assert latest.id == s2.id


def test_latest_session_none(store):
    assert store.latest_session("ghost") is None


# ── messages ──────────────────────────────────────────────────────────────


def test_add_and_retrieve_message(store):
    s = store.create_session("p")
    m = store.add_message(s.id, "user", "hello there")
    assert m.id > 0
    assert m.role == "user"
    assert m.content == "hello there"


def test_messages_order(store):
    s = store.create_session("p")
    store.add_message(s.id, "user", "first")
    store.add_message(s.id, "assistant", "second")
    store.add_message(s.id, "user", "third")
    msgs = store.messages(s.id)
    assert [m.content for m in msgs] == ["first", "second", "third"]


def test_messages_empty(store):
    s = store.create_session("p")
    assert store.messages(s.id) == []


def test_append_to_message(store):
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "")
    store.append_to_message(m.id, "Hello")
    store.append_to_message(m.id, " world")
    msgs = store.messages(s.id)
    assert msgs[0].content == "Hello world"


def test_set_message_content(store):
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "old")
    store.set_message_content(m.id, "new content")
    msgs = store.messages(s.id)
    assert msgs[0].content == "new content"


def test_set_message_artifacts(store):
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "")
    artifacts = [{"path": "/tmp/plot.png", "rel_path": "plot.png", "mime": "image/png"}]
    store.set_message_artifacts(m.id, artifacts)
    msgs = store.messages(s.id)
    assert msgs[0].artifacts == artifacts


def test_add_message_with_attachments(store):
    s = store.create_session("p")
    atts = [{"filename": "data.csv", "path": "/tmp/data.csv", "size": 100}]
    m = store.add_message(s.id, "user", "see attached", attachments=atts)
    msgs = store.messages(s.id)
    assert msgs[0].attachments == atts


def test_add_message_bumps_session_activity(store):
    s = store.create_session("p")
    t0 = s.last_active_at
    time.sleep(0.01)
    store.add_message(s.id, "user", "hi")
    got = store.get_session(s.id)
    assert got.last_active_at > t0


def test_messages_limit(store):
    s = store.create_session("p")
    for i in range(10):
        store.add_message(s.id, "user", f"msg{i}")
    msgs = store.messages(s.id, limit=5)
    assert len(msgs) == 5
    # Should return first 5 (ordered by id ASC)
    assert msgs[0].content == "msg0"
    assert msgs[4].content == "msg4"
