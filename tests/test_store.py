"""Tests for lmc/store.py — Store CRUD + streaming helpers."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from lmc.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(db_path=tmp_path / "test.db")


# ── sessions ──────────────────────────────────────────────────────────────


def test_create_session(store: Store) -> None:
    s = store.create_session("proj1")
    assert s.project == "proj1"
    assert s.id
    assert s.claude_session_id is None


def test_get_session(store: Store) -> None:
    s = store.create_session("proj1")
    s2 = store.get_session(s.id)
    assert s2 is not None
    assert s2.id == s.id
    assert s2.project == "proj1"


def test_get_session_missing(store: Store) -> None:
    assert store.get_session("nonexistent") is None


def test_list_sessions(store: Store) -> None:
    store.create_session("a")
    store.create_session("a")
    store.create_session("b")
    assert len(store.list_sessions("a")) == 2
    assert len(store.list_sessions("b")) == 1


def test_list_sessions_all(store: Store) -> None:
    store.create_session("a")
    store.create_session("b")
    assert len(store.list_sessions()) == 2


def test_list_sessions_empty(store: Store) -> None:
    assert store.list_sessions("nope") == []


def test_update_session_claude_id(store: Store) -> None:
    s = store.create_session("p")
    store.update_session(s.id, claude_session_id="abc123")
    s2 = store.get_session(s.id)
    assert s2 is not None
    assert s2.claude_session_id == "abc123"


def test_update_session_bumps_activity(store: Store) -> None:
    s = store.create_session("p")
    before = s.last_active_at
    time.sleep(0.05)
    store.update_session(s.id)
    s2 = store.get_session(s.id)
    assert s2 is not None
    assert s2.last_active_at > before


def test_delete_session(store: Store) -> None:
    s = store.create_session("p")
    store.delete_session(s.id)
    assert store.get_session(s.id) is None


def test_delete_session_cascades_messages(store: Store) -> None:
    s = store.create_session("p")
    store.add_message(s.id, "user", "hello")
    store.delete_session(s.id)
    assert store.messages(s.id) == []


def test_latest_session(store: Store) -> None:
    s1 = store.create_session("p")
    time.sleep(0.02)
    s2 = store.create_session("p")
    latest = store.latest_session("p")
    assert latest is not None
    assert latest.id == s2.id


def test_latest_session_none(store: Store) -> None:
    assert store.latest_session("ghost") is None


# ── messages ──────────────────────────────────────────────────────────────


def test_add_and_retrieve_message(store: Store) -> None:
    s = store.create_session("p")
    m = store.add_message(s.id, "user", "hello")
    msgs = store.messages(s.id)
    assert len(msgs) == 1
    assert msgs[0].content == "hello"
    assert msgs[0].role == "user"
    assert msgs[0].id == m.id


def test_messages_order(store: Store) -> None:
    s = store.create_session("p")
    for i in range(5):
        store.add_message(s.id, "user", str(i))
    msgs = store.messages(s.id)
    contents = [m.content for m in msgs]
    assert contents == [str(i) for i in range(5)]


def test_messages_empty(store: Store) -> None:
    s = store.create_session("p")
    assert store.messages(s.id) == []


def test_append_to_message(store: Store) -> None:
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "Hello")
    store.append_to_message(m.id, " world")
    msgs = store.messages(s.id)
    assert msgs[0].content == "Hello world"


def test_set_message_content(store: Store) -> None:
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "draft")
    store.set_message_content(m.id, "final")
    msgs = store.messages(s.id)
    assert msgs[0].content == "final"


def test_set_message_artifacts(store: Store) -> None:
    s = store.create_session("p")
    m = store.add_message(s.id, "assistant", "")
    arts = [{"path": "/tmp/a.png", "mime": "image/png", "size": 10}]
    store.set_message_artifacts(m.id, arts)
    msgs = store.messages(s.id)
    assert msgs[0].artifacts == arts


def test_add_message_with_attachments(store: Store) -> None:
    s = store.create_session("p")
    attachments = [{"filename": "file.pdf", "path": "/tmp/f.pdf"}]
    m = store.add_message(s.id, "user", "see attached", attachments=attachments)
    msgs = store.messages(s.id)
    assert msgs[0].attachments == attachments


def test_add_message_bumps_session_activity(store: Store) -> None:
    s = store.create_session("p")
    t0 = s.last_active_at
    time.sleep(0.05)
    store.add_message(s.id, "user", "ping")
    s2 = store.get_session(s.id)
    assert s2 is not None
    assert s2.last_active_at > t0


def test_messages_limit(store: Store) -> None:
    s = store.create_session("p")
    for i in range(20):
        store.add_message(s.id, "user", str(i))
    msgs = store.messages(s.id, limit=5)
    assert len(msgs) == 5
    assert msgs[0].content == "0"
