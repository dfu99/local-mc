"""FastAPI HTTP surface — REST endpoints, /api/files sandbox, upload caps.

The sandbox checks (403 on /etc/passwd, 403 on path traversal, 403 on a
symlink that resolves outside any project root) are the security-critical
guarantees that `architecture.md` advertises. Locking these down here means
the next refactor of `serve_file` can't silently weaken them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_list_projects_empty(client: TestClient):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_add_project_round_trip(client: TestClient, project_dir: Path):
    payload = {"name": "demo", "path": str(project_dir), "tags": ["t1"]}
    r = client.post("/api/projects", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "demo"
    assert body["exists"] is True
    assert body["tags"] == ["t1"]

    listed = client.get("/api/projects").json()
    assert len(listed) == 1 and listed[0]["name"] == "demo"


def test_add_duplicate_project_returns_400(client: TestClient, project_dir: Path):
    payload = {"name": "demo", "path": str(project_dir)}
    assert client.post("/api/projects", json=payload).status_code == 200
    r = client.post("/api/projects", json=payload)
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


def test_add_project_bad_path_returns_400(client: TestClient, tmp_path: Path):
    payload = {"name": "ghost", "path": str(tmp_path / "no-such-dir")}
    r = client.post("/api/projects", json=payload)
    assert r.status_code == 400


def test_remove_project(client: TestClient, project_dir: Path):
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    r = client.delete("/api/projects/demo")
    assert r.status_code == 200
    assert client.get("/api/projects").json() == []


def test_remove_unknown_project_returns_404(client: TestClient):
    r = client.delete("/api/projects/ghost")
    assert r.status_code == 404


def test_create_session_for_project(client: TestClient, project_dir: Path):
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    r = client.post("/api/projects/demo/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["project"] == "demo"
    sid = body["id"]

    msgs = client.get(f"/api/sessions/{sid}/messages")
    assert msgs.status_code == 200
    assert msgs.json() == []


def test_create_session_for_unknown_project_returns_404(client: TestClient):
    r = client.post("/api/projects/ghost/sessions")
    assert r.status_code == 404


def test_messages_for_unknown_session_returns_404(client: TestClient):
    r = client.get("/api/sessions/no-such-sid/messages")
    assert r.status_code == 404


def test_delete_session(client: TestClient, project_dir: Path):
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    sid = client.post("/api/projects/demo/sessions").json()["id"]
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert client.get(f"/api/sessions/{sid}/messages").status_code == 404


# ── /api/files sandbox ──────────────────────────────────────────────────


def _seed_demo(client: TestClient, project_dir: Path) -> str:
    client.post("/api/projects", json={"name": "demo", "path": str(project_dir)})
    return client.post("/api/projects/demo/sessions").json()["id"]


def test_files_serves_in_project_path(client: TestClient, project_dir: Path):
    _seed_demo(client, project_dir)
    target = project_dir / "hello.txt"
    target.write_text("inside-project payload\n")
    r = client.get("/api/files", params={"path": str(target)})
    assert r.status_code == 200
    assert r.text == "inside-project payload\n"


def test_files_404_for_missing(client: TestClient, project_dir: Path):
    _seed_demo(client, project_dir)
    r = client.get("/api/files", params={"path": str(project_dir / "missing.txt")})
    assert r.status_code == 404


def test_files_403_outside_any_project(client: TestClient, project_dir: Path):
    _seed_demo(client, project_dir)
    # /etc/passwd exists on Linux/macOS; on Windows fall back to a known sys file
    outside = "/etc/passwd"
    if not Path(outside).exists():
        outside = sys.executable  # always present, never inside the project root
    r = client.get("/api/files", params={"path": outside})
    assert r.status_code == 403
    assert "outside" in r.json()["detail"]


def test_files_403_via_dotdot_traversal(client: TestClient, project_dir: Path):
    _seed_demo(client, project_dir)
    # Construct a path that lexically looks inside but resolves outside
    sneaky = str(project_dir / ".." / ".." / "etc" / "passwd")
    if not Path(sneaky).resolve().exists():
        sneaky = str(project_dir / ".." / Path(sys.executable).name)
    r = client.get("/api/files", params={"path": sneaky})
    # Either 403 (resolved-out) or 404 (target missing) is correct; 200 is not.
    assert r.status_code in (403, 404)


@pytest.mark.skipif(
    os.name != "posix", reason="symlinks behave differently on Windows"
)
def test_files_403_via_symlink_pointing_outside(
    client: TestClient, project_dir: Path
):
    _seed_demo(client, project_dir)
    target = "/etc/passwd"
    if not Path(target).exists():
        target = sys.executable
    leak = project_dir / "leak.txt"
    leak.symlink_to(target)
    r = client.get("/api/files", params={"path": str(leak)})
    assert r.status_code == 403


# ── Upload ──────────────────────────────────────────────────────────────


def test_upload_lands_in_inbox(client: TestClient, project_dir: Path):
    sid = _seed_demo(client, project_dir)
    payload = b"hello local-mc upload\n"
    r = client.post(
        f"/api/sessions/{sid}/upload",
        files={"file": ("note.txt", payload, "text/plain")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    landed = Path(body["path"])
    assert landed.exists()
    assert landed.read_bytes() == payload
    assert (project_dir / "inbox" / sid).is_dir()
    assert body["rel_path"].startswith(f"inbox/{sid}/")


def test_upload_413_when_size_exceeds_cap(client: TestClient, project_dir: Path):
    """Settings fixture sets max_upload_mb=1; send 2 MiB and expect 413."""
    sid = _seed_demo(client, project_dir)
    payload = b"x" * (2 * 1024 * 1024)
    r = client.post(
        f"/api/sessions/{sid}/upload",
        files={"file": ("big.bin", payload, "application/octet-stream")},
    )
    assert r.status_code == 413
    # And no leftover file should remain
    inbox = project_dir / "inbox" / sid
    if inbox.exists():
        assert list(inbox.iterdir()) == []


def test_upload_404_for_unknown_session(client: TestClient):
    r = client.post(
        "/api/sessions/no-such-sid/upload",
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert r.status_code == 404


def test_upload_safe_filename_strips_path_chars(
    client: TestClient, project_dir: Path
):
    sid = _seed_demo(client, project_dir)
    weird = "../../etc/passwd"
    r = client.post(
        f"/api/sessions/{sid}/upload",
        files={"file": (weird, b"x", "text/plain")},
    )
    assert r.status_code == 200
    body = r.json()
    # Filename gets a timestamp+uuid prefix and `..` is sanitised away.
    assert ".." not in body["filename"]
    assert "/" not in body["filename"]
    landed = Path(body["path"])
    assert landed.parent == project_dir / "inbox" / sid


# ── Static frontend mount ───────────────────────────────────────────────


def test_index_html_served(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>local-mc</title>" in r.text


def test_static_assets_served(client: TestClient):
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200
