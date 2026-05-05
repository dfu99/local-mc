"""SQLite store: sessions, messages, streaming append.

The streaming append path is the one `tasks/lessons.md` flagged as risky —
"verify with a test that streams 100 deltas into one message and re-reads
it." That's `test_append_to_message_under_streaming` below.
"""
from __future__ import annotations

import time

from lmc.store import Store


def test_create_session_round_trips(store: Store):
    s = store.create_session("demo")
    assert s.project == "demo"
    assert s.claude_session_id is None
    fetched = store.get_session(s.id)
    assert fetched is not None and fetched.id == s.id


def test_get_unknown_session_returns_none(store: Store):
    assert store.get_session("does-not-exist") is None


def test_latest_session_picks_most_recent(store: Store):
    a = store.create_session("demo")
    time.sleep(0.01)
    b = store.create_session("demo")
    latest = store.latest_session("demo")
    assert latest is not None and latest.id == b.id
    assert latest.id != a.id


def test_list_sessions_filters_by_project(store: Store):
    store.create_session("alpha")
    store.create_session("beta")
    store.create_session("alpha")
    assert len(store.list_sessions("alpha")) == 2
    assert len(store.list_sessions("beta")) == 1
    assert len(store.list_sessions()) == 3


def test_update_session_records_claude_id(store: Store):
    s = store.create_session("demo")
    store.update_session(s.id, claude_session_id="claude-abc-123")
    refreshed = store.get_session(s.id)
    assert refreshed is not None
    assert refreshed.claude_session_id == "claude-abc-123"


def test_delete_session_cascades_messages(store: Store):
    s = store.create_session("demo")
    store.add_message(s.id, "user", "hello")
    store.add_message(s.id, "assistant", "hi back")
    assert len(store.messages(s.id)) == 2
    store.delete_session(s.id)
    assert store.get_session(s.id) is None
    assert store.messages(s.id) == []


def test_add_message_with_attachments_and_artifacts(store: Store):
    s = store.create_session("demo")
    m = store.add_message(
        s.id,
        "user",
        "see file",
        attachments=[{"filename": "a.png", "size": 12}],
        artifacts=[{"path": "/tmp/x.png"}],
    )
    fetched = store.messages(s.id)[0]
    assert fetched.id == m.id
    assert fetched.attachments == [{"filename": "a.png", "size": 12}]
    assert fetched.artifacts == [{"path": "/tmp/x.png"}]


def test_append_to_message_under_streaming(store: Store):
    """Stream 100 deltas into one assistant message and re-read.

    Per `tasks/lessons.md`: this is the most fragile part of the store.
    """
    s = store.create_session("demo")
    m = store.add_message(s.id, "assistant", "")
    deltas = [f"chunk-{i:03d} " for i in range(100)]
    for d in deltas:
        store.append_to_message(m.id, d)

    fetched = store.messages(s.id)[0]
    assert fetched.content == "".join(deltas)
    assert fetched.content.startswith("chunk-000 ")
    assert fetched.content.endswith("chunk-099 ")


def test_set_message_content_replaces(store: Store):
    s = store.create_session("demo")
    m = store.add_message(s.id, "assistant", "old")
    store.set_message_content(m.id, "new")
    assert store.messages(s.id)[0].content == "new"


def test_set_message_artifacts_round_trips(store: Store):
    s = store.create_session("demo")
    m = store.add_message(s.id, "assistant", "x")
    arts = [{"path": "/tmp/a.png", "mime": "image/png"}]
    store.set_message_artifacts(m.id, arts)
    assert store.messages(s.id)[0].artifacts == arts


def test_messages_ordered_by_id(store: Store):
    s = store.create_session("demo")
    for i in range(5):
        store.add_message(s.id, "user", f"m{i}")
    msgs = store.messages(s.id)
    assert [m.content for m in msgs] == [f"m{i}" for i in range(5)]


def test_session_last_active_bumps_on_message(store: Store):
    s = store.create_session("demo")
    initial = store.get_session(s.id)
    assert initial is not None
    initial_active = initial.last_active_at
    time.sleep(0.02)
    store.add_message(s.id, "user", "hello")
    bumped = store.get_session(s.id)
    assert bumped is not None
    assert bumped.last_active_at > initial_active


def test_update_session_no_args_no_op(store: Store):
    s = store.create_session("demo")
    pre = store.get_session(s.id)
    assert pre is not None
    # bump_activity defaults true; pass False to verify no-op path
    store.update_session(s.id, bump_activity=False)
    post = store.get_session(s.id)
    assert post is not None
    assert post.last_active_at == pre.last_active_at
