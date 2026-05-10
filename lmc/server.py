"""FastAPI server for the local-mc web UI.

Endpoints:
    GET    /api/projects                 list registered projects
    POST   /api/projects                 add a project
    DELETE /api/projects/{name}          remove a project
    GET    /api/projects/{name}/sessions list sessions for a project
    POST   /api/projects/{name}/sessions create a fresh session
    GET    /api/sessions/{sid}/messages  history for a session
    POST   /api/sessions/{sid}/upload    upload an attachment
    GET    /api/files                    serve a file from a project's tree
    WS     /api/sessions/{sid}/chat      stream a turn

Security: binds to 127.0.0.1 by default. CORS is locked to localhost. The
``/api/files`` endpoint refuses to serve paths outside any registered project
root, to prevent the browser from reading arbitrary files.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import artifacts as artifacts_mod
from .config import Paths, Settings, get_paths, load_settings
from .projects import Project, ProjectError, Registry
from .sessions import AgentEvent, make_agent
from .store import Store


# ── Pydantic models for request/response ───────────────────────────────


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    path: str
    tags: list[str] = []
    description: str = ""


class ProjectOut(BaseModel):
    name: str
    path: str
    tags: list[str]
    description: str
    exists: bool


class SessionOut(BaseModel):
    id: str
    project: str
    created_at: float
    last_active_at: float


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    attachments: list[dict]
    artifacts: list[dict]
    created_at: float


# ── App factory ─────────────────────────────────────────────────────────


def create_app(
    paths: Paths | None = None,
    settings: Settings | None = None,
    web_dir: Path | None = None,
) -> FastAPI:
    resolved_paths: Paths = paths or get_paths()
    resolved_paths.ensure()
    resolved_settings: Settings = settings or load_settings(resolved_paths)
    registry = Registry(resolved_paths)
    store = Store(paths=resolved_paths)

    if web_dir is None:
        # Bundled with the package: lmc/web/. The legacy top-level web/
        # directory at the repo root is no longer used (q07 — Windows
        # wheel portability).
        web_dir = Path(__file__).resolve().parent / "web"

    app = FastAPI(title="local-mc", version="0.1.0")

    # Localhost only — never permit cross-origin from outside the loopback.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://127.0.0.1",
            f"http://localhost:{resolved_settings.port}",
            f"http://127.0.0.1:{resolved_settings.port}",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Projects ────────────────────────────────────────────────────

    @app.get("/api/projects", response_model=list[ProjectOut])
    def list_projects() -> list[ProjectOut]:
        return [
            ProjectOut(
                name=p.name,
                path=p.path,
                tags=p.tags,
                description=p.description,
                exists=p.exists_on_disk(),
            )
            for p in registry.load()
        ]

    @app.post("/api/projects", response_model=ProjectOut)
    def add_project(payload: ProjectIn) -> ProjectOut:
        try:
            p = registry.add(
                payload.name,
                payload.path,
                tags=payload.tags,
                description=payload.description,
            )
        except ProjectError as e:
            raise HTTPException(400, str(e))
        return ProjectOut(
            name=p.name,
            path=p.path,
            tags=p.tags,
            description=p.description,
            exists=p.exists_on_disk(),
        )

    @app.delete("/api/projects/{name}")
    def remove_project(name: str):
        try:
            registry.remove(name)
        except ProjectError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    # ── Sessions ────────────────────────────────────────────────────

    @app.get("/api/projects/{name}/sessions", response_model=list[SessionOut])
    def list_sessions(name: str) -> list[SessionOut]:
        if not registry.get(name):
            raise HTTPException(404, f"project not found: {name}")
        return [
            SessionOut(
                id=s.id,
                project=s.project,
                created_at=s.created_at,
                last_active_at=s.last_active_at,
            )
            for s in store.list_sessions(name)
        ]

    @app.post("/api/projects/{name}/sessions", response_model=SessionOut)
    def create_session(name: str) -> SessionOut:
        if not registry.get(name):
            raise HTTPException(404, f"project not found: {name}")
        s = store.create_session(name)
        return SessionOut(
            id=s.id,
            project=s.project,
            created_at=s.created_at,
            last_active_at=s.last_active_at,
        )

    @app.delete("/api/sessions/{sid}")
    def delete_session(sid: str):
        if not store.get_session(sid):
            raise HTTPException(404, "session not found")
        store.delete_session(sid)
        return {"ok": True}

    @app.get("/api/sessions/{sid}/messages", response_model=list[MessageOut])
    def session_messages(sid: str) -> list[MessageOut]:
        if not store.get_session(sid):
            raise HTTPException(404, "session not found")
        return [
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                attachments=m.attachments,
                artifacts=m.artifacts,
                created_at=m.created_at,
            )
            for m in store.messages(sid)
        ]

    # ── Uploads ─────────────────────────────────────────────────────

    @app.post("/api/sessions/{sid}/upload")
    async def upload_attachment(sid: str, file: UploadFile):
        sess = store.get_session(sid)
        if not sess:
            raise HTTPException(404, "session not found")
        proj = registry.get(sess.project)
        if not proj:
            raise HTTPException(404, "project not found")

        max_bytes = resolved_settings.max_upload_mb * 1024 * 1024
        # Save into the project's inbox/<session>/ so the agent can read it.
        target_dir = Path(proj.path) / "inbox" / sid
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(file.filename or "upload")
        target = target_dir / safe_name

        size = 0
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        413,
                        f"upload exceeds {resolved_settings.max_upload_mb} MB limit",
                    )
                out.write(chunk)

        return {
            "filename": safe_name,
            "path": str(target),
            "rel_path": str(target.relative_to(proj.path)),
            "size": size,
            "mime": file.content_type
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream",
        }

    # ── File serving (artifacts and attachments) ────────────────────

    @app.get("/api/files")
    def serve_file(path: str):
        """Serve a file from any registered project's tree.

        We resolve the requested path and confirm it's under one of the
        registered project roots — otherwise refuse. This prevents the
        browser from reading arbitrary files just because the server can.
        """
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            raise HTTPException(404, "file not found")
        ok = False
        for p in registry.load():
            try:
                root = Path(p.path).resolve()
            except OSError:
                continue
            try:
                target.relative_to(root)
                ok = True
                break
            except ValueError:
                continue
        if not ok:
            raise HTTPException(403, "path is outside any registered project")
        return FileResponse(target)

    # ── WebSocket: streaming chat ───────────────────────────────────

    @app.websocket("/api/sessions/{sid}/chat")
    async def chat_ws(ws: WebSocket, sid: str):
        await ws.accept()
        sess = store.get_session(sid)
        if not sess:
            await ws.send_json({"type": "error", "message": "session not found"})
            await ws.close()
            return
        proj = registry.get(sess.project)
        if not proj:
            await ws.send_json({"type": "error", "message": "project not found"})
            await ws.close()
            return

        agent = make_agent(resolved_settings)
        # Track the in-flight turn so a {"type": "cancel"} from the client
        # can stop it. Holding it on the closure (not module state) keeps
        # cancels scoped to this WS connection — disconnecting one tab
        # doesn't kill another tab's turn.
        current_turn: asyncio.Task | None = None

        async def run_turn(payload: dict) -> None:
            user_text = payload.get("text", "")
            attachments = payload.get("attachments", []) or []
            attachment_paths = [a.get("path") for a in attachments if a.get("path")]

            assistant_msg = None
            try:
                user_msg = store.add_message(
                    sid, "user", user_text, attachments=attachments
                )
                await ws.send_json(
                    {"type": "user_message", "message": _msg_to_dict(user_msg)}
                )

                assistant_msg = store.add_message(sid, "assistant", "")
                await ws.send_json(
                    {"type": "assistant_start", "message_id": assistant_msg.id}
                )

                snap = artifacts_mod.snapshot(
                    proj.path, globs=resolved_settings.artifact_globs
                )

                # Re-fetch session so we pick up any claude_session_id written
                # by a previous turn on the same socket.
                turn_sess = store.get_session(sid) or sess

                async for ev in _run_turn(
                    agent,
                    user_text,
                    proj=proj,
                    sess=turn_sess,
                    store=store,
                    attachment_paths=attachment_paths,
                ):
                    if ev.type == "text":
                        store.append_to_message(assistant_msg.id, ev.data["text"])
                        await ws.send_json(
                            {
                                "type": "delta",
                                "message_id": assistant_msg.id,
                                "text": ev.data["text"],
                            }
                        )
                    elif ev.type in ("tool_use", "tool_result"):
                        await ws.send_json(
                            {
                                "type": ev.type,
                                "message_id": assistant_msg.id,
                                "data": ev.data,
                            }
                        )
                    elif ev.type == "session_id":
                        store.update_session(
                            sid, claude_session_id=ev.data["session_id"]
                        )
                    elif ev.type == "done":
                        new_artifacts = [
                            a.to_dict()
                            for a in artifacts_mod.diff(
                                proj.path,
                                snap,
                                globs=resolved_settings.artifact_globs,
                            )
                        ]
                        store.set_message_artifacts(assistant_msg.id, new_artifacts)
                        await ws.send_json(
                            {
                                "type": "done",
                                "message_id": assistant_msg.id,
                                "artifacts": new_artifacts,
                                "stats": ev.data,
                            }
                        )
                    elif ev.type == "error":
                        await ws.send_json(
                            {
                                "type": "error",
                                "message_id": assistant_msg.id,
                                "message": ev.data.get("message", "agent error"),
                            }
                        )
            except asyncio.CancelledError:
                # Surface the cancel back to the client so it can flip its
                # streaming UI off. Best-effort — if the socket is already
                # gone, silently swallow.
                if assistant_msg is not None:
                    try:
                        await ws.send_json(
                            {
                                "type": "cancelled",
                                "message_id": assistant_msg.id,
                            }
                        )
                    except Exception:
                        pass
                raise

        try:
            while True:
                payload = await ws.receive_json()
                kind = payload.get("type")

                if kind == "ping":
                    await ws.send_json({"type": "pong"})
                    continue

                if kind == "cancel":
                    if current_turn and not current_turn.done():
                        current_turn.cancel()
                        try:
                            await current_turn
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                    # else: idle — cancel is a no-op so the client can spam it
                    # without a server round-trip, matches mc steer's idempotency.
                    continue

                if kind != "message":
                    await ws.send_json(
                        {"type": "error", "message": "expected type=message"}
                    )
                    continue

                if current_turn and not current_turn.done():
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": "turn already in progress; send cancel first",
                        }
                    )
                    continue

                current_turn = asyncio.create_task(run_turn(payload))
        except WebSocketDisconnect:
            if current_turn and not current_turn.done():
                current_turn.cancel()
                try:
                    await current_turn
                except (asyncio.CancelledError, Exception):
                    pass
            return
        except Exception as e:  # pragma: no cover - defensive
            try:
                await ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    # ── /status — minimal project status panel ──────────────────────

    @app.get("/status")
    def status_panel():
        """Read-only HTML view: every project + its latest session.

        Mirrors `mc status` from the original Mission Control. Projects
        with idle time > 1 hour are flagged red so the operator can spot
        sessions that need attention. Self-contained HTML — no JS, no
        external CSS — so it can be wget'd or curl'd for scripted alerts.
        """
        from datetime import datetime, timezone
        from html import escape

        from fastapi.responses import HTMLResponse

        idle_red_seconds = 60 * 60
        now = time.time()
        rows: list[str] = []
        for proj in registry.load():
            sess = store.latest_session(proj.name)
            tags = ", ".join(proj.tags) if proj.tags else ""
            if sess is None:
                rows.append(
                    f"<tr class='no-session'>"
                    f"<td>{escape(proj.name)}</td>"
                    f"<td>{escape(proj.path)}</td>"
                    f"<td>{escape(tags)}</td>"
                    f"<td>—</td><td>(no session)</td><td>—</td></tr>"
                )
                continue
            idle = now - sess.last_active_at
            klass = "stale" if idle > idle_red_seconds else "active"
            last_active = datetime.fromtimestamp(
                sess.last_active_at, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%SZ")
            idle_human = _humanize_idle(idle)
            rows.append(
                f"<tr class='{klass}'>"
                f"<td>{escape(proj.name)}</td>"
                f"<td>{escape(proj.path)}</td>"
                f"<td>{escape(tags)}</td>"
                f"<td>{escape(sess.id[:8])}</td>"
                f"<td>{last_active}</td>"
                f"<td>{idle_human}</td></tr>"
            )

        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>local-mc status</title>"
            "<style>"
            "body{font-family:system-ui,sans-serif;margin:24px;}"
            "table{border-collapse:collapse;width:100%;}"
            "th,td{padding:6px 12px;border-bottom:1px solid #ddd;text-align:left;}"
            "th{background:#f5f5f5;}"
            "tr.stale{background:#fff0f0;color:#8a1f1f;}"
            "tr.no-session{color:#888;}"
            "code{font-size:90%;}"
            "</style></head><body>"
            "<h1>local-mc status</h1>"
            f"<p>{len(rows)} project(s) — refreshed at "
            f"{datetime.fromtimestamp(now, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}. "
            "Rows in red are idle > 1 h.</p>"
            "<table><thead><tr>"
            "<th>Project</th><th>Path</th><th>Tags</th><th>Session</th>"
            "<th>Last active</th><th>Idle</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            "</body></html>"
        )
        return HTMLResponse(body)

    # ── Static frontend ─────────────────────────────────────────────

    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    else:

        @app.get("/")
        def root_placeholder():
            return JSONResponse(
                {
                    "name": "local-mc",
                    "version": "0.1.0",
                    "note": (
                        "Web UI not found at "
                        f"{web_dir}; install or set --web-dir."
                    ),
                }
            )

    # Stash for tests / introspection
    app.state.paths = resolved_paths
    app.state.settings = resolved_settings
    app.state.registry = registry
    app.state.store = store

    return app


# ── Helpers ─────────────────────────────────────────────────────────────


async def _run_turn(
    agent,
    user_text: str,
    *,
    proj: Project,
    sess,
    store: Store,
    attachment_paths: list[str],
) -> AsyncIterator[AgentEvent]:
    async for ev in agent.stream(
        user_text,
        cwd=proj.path,
        claude_session_id=sess.claude_session_id,
        attachments=attachment_paths,
    ):
        yield ev


def _msg_to_dict(m) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "attachments": m.attachments,
        "artifacts": m.artifacts,
        "created_at": m.created_at,
    }


def _humanize_idle(seconds: float) -> str:
    """Render idle seconds as `12s` / `4m` / `2h 13m` / `1d 4h`."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _safe_filename(name: str) -> str:
    """Strip path components and known bad chars; keep dots and dashes."""
    name = os.path.basename(name)
    out = []
    for ch in name:
        if ch.isalnum() or ch in "._-":
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("._") or "upload"
    if len(cleaned) > 200:
        cleaned = cleaned[-200:]
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}-{cleaned}"
