"""``lmc`` — local-mc command-line entry point.

Subcommands:
    lmc serve [--host H] [--port P] [--no-open]
    lmc add <name> <path> [--tags ...] [--desc TEXT]
    lmc rm <name>
    lmc list
    lmc settings [--get KEY | --set KEY=VAL ...]
    lmc init                              create config dir + write defaults
    lmc send <project> "msg"              send a message to the latest
                                          (or new) session and stream events

The CLI is intentionally narrow. The web UI is the primary interface; this
exists so a fresh-clone setup can register projects and start the server in
two commands.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .config import Settings, get_paths, load_settings, save_settings
from .projects import ProjectError, Registry


def _cmd_init(args: argparse.Namespace) -> int:
    paths = get_paths()
    paths.ensure()
    if not paths.settings_yaml.exists():
        save_settings(Settings(), paths)
    if not paths.projects_yaml.exists():
        Registry(paths).save([])
    print(f"config dir: {paths.config_dir}")
    print(f"state dir:  {paths.state_dir}")
    print(f"settings:   {paths.settings_yaml}")
    print(f"projects:   {paths.projects_yaml}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    reg = Registry()
    try:
        p = reg.add(args.name, args.path, tags=args.tags or [], description=args.desc or "")
    except ProjectError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"added: {p.name} → {p.path}")
    return 0


def _cmd_rm(args: argparse.Namespace) -> int:
    reg = Registry()
    try:
        reg.remove(args.name)
    except ProjectError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"removed: {args.name}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    reg = Registry()
    projects = reg.load()
    if not projects:
        print("(no projects registered — try `lmc add <name> <path>`)")
        return 0
    width = max((len(p.name) for p in projects), default=10)
    for p in projects:
        marker = " " if p.exists_on_disk() else "!"
        tags = ",".join(p.tags) if p.tags else ""
        print(f"{marker} {p.name:<{width}}  {p.path}  {tags}")
    return 0


def _cmd_settings(args: argparse.Namespace) -> int:
    paths = get_paths()
    s = load_settings(paths)
    if args.get_key:
        if not hasattr(s, args.get_key):
            print(f"unknown setting: {args.get_key}", file=sys.stderr)
            return 1
        print(getattr(s, args.get_key))
        return 0
    if args.set_pairs:
        for pair in args.set_pairs:
            if "=" not in pair:
                print(f"bad --set value: {pair} (expected KEY=VAL)", file=sys.stderr)
                return 1
            k, v = pair.split("=", 1)
            if not hasattr(s, k):
                print(f"unknown setting: {k}", file=sys.stderr)
                return 1
            current = getattr(s, k)
            if isinstance(current, bool):
                v_typed = v.lower() in ("1", "true", "yes", "on")
            elif isinstance(current, int):
                v_typed = int(v)
            else:
                v_typed = v
            setattr(s, k, v_typed)
        save_settings(s, paths)
        print(f"settings updated: {paths.settings_yaml}")
        return 0
    # No args: dump all
    out = {f: getattr(s, f) for f in s.__dataclass_fields__}
    print(json.dumps(out, indent=2, default=str))
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    """Send a message to a project's latest session (creating one if needed).

    Streams the agent's text deltas to stdout, then prints a final summary.
    Useful for scripted workflows — mirrors `mc send` from the original
    Mission Control. The chat input in the browser is the primary surface;
    this is for automation.
    """
    import asyncio

    from .config import load_settings
    from .sessions import make_agent
    from .store import Store

    paths = get_paths()
    paths.ensure()
    settings = load_settings(paths)

    reg = Registry(paths)
    proj = reg.get(args.project)
    if proj is None:
        print(f"error: unknown project '{args.project}'", file=sys.stderr)
        return 1
    if not proj.exists_on_disk():
        print(f"error: project path missing: {proj.path}", file=sys.stderr)
        return 1

    store = Store(paths=paths)
    sess = store.latest_session(args.project) or store.create_session(args.project)
    store.add_message(sess.id, "user", args.message)

    agent = make_agent(settings)

    async def _run() -> int:
        msg = store.add_message(sess.id, "assistant", "")
        last_session_id = sess.claude_session_id
        async for ev in agent.stream(
            args.message,
            cwd=proj.path,
            claude_session_id=last_session_id,
            attachments=None,
        ):
            if ev.type == "text":
                store.append_to_message(msg.id, ev.data["text"])
                if not args.quiet:
                    print(ev.data["text"], end="", flush=True)
            elif ev.type == "session_id":
                last_session_id = ev.data["session_id"]
                store.update_session(sess.id, claude_session_id=last_session_id)
            elif ev.type == "error":
                print(
                    f"\n[error] {ev.data.get('message', 'agent error')}",
                    file=sys.stderr,
                )
                return 2
            elif ev.type == "done":
                if not args.quiet:
                    print()  # newline after streaming text
                stats = ev.data
                print(
                    f"[done] session={sess.id[:8]} "
                    f"duration_ms={stats.get('duration_ms')} "
                    f"cost_usd={stats.get('total_cost_usd')}"
                )
        return 0

    return asyncio.run(_run())


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print(
            "error: uvicorn not installed. run `pip install -e .` or "
            "`pip install -r requirements.txt`",
            file=sys.stderr,
        )
        return 2

    paths = get_paths()
    paths.ensure()
    settings = load_settings(paths)
    host = args.host or settings.host
    port = args.port or settings.port
    web_dir = Path(args.web_dir).expanduser() if args.web_dir else None

    # Build an explicit app factory closure so uvicorn workers wouldn't try to
    # re-import a string path that doesn't carry our paths/settings overrides.
    from .server import create_app

    app = create_app(paths=paths, settings=settings, web_dir=web_dir)

    url = f"http://{host}:{port}"
    print(f"local-mc listening on {url}")
    if settings.auto_open_browser and not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover
            pass

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lmc", description="local Mission Control")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="create config + state dirs with defaults")
    sp.set_defaults(func=_cmd_init)

    sp = sub.add_parser("serve", help="start the web UI server")
    sp.add_argument("--host", help="bind address (default: 127.0.0.1)")
    sp.add_argument("--port", type=int, help="port (default: 8765)")
    sp.add_argument(
        "--no-open", action="store_true", help="don't auto-open browser"
    )
    sp.add_argument(
        "--web-dir",
        help="path to the web/ directory (defaults to package's bundled UI)",
    )
    sp.set_defaults(func=_cmd_serve)

    sp = sub.add_parser("add", help="register a project")
    sp.add_argument("name")
    sp.add_argument("path")
    sp.add_argument("--tags", nargs="*")
    sp.add_argument("--desc", help="short description")
    sp.set_defaults(func=_cmd_add)

    sp = sub.add_parser("rm", help="remove a project")
    sp.add_argument("name")
    sp.set_defaults(func=_cmd_rm)

    sp = sub.add_parser("list", help="list registered projects")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("settings", help="get/set runtime settings")
    sp.add_argument("--get", dest="get_key", help="print one setting and exit")
    sp.add_argument(
        "--set",
        dest="set_pairs",
        nargs="*",
        help="set KEY=VAL (repeat to set multiple)",
    )
    sp.set_defaults(func=_cmd_settings)

    sp = sub.add_parser(
        "send",
        help="send a message to a project's latest session (or create one)",
    )
    sp.add_argument("project", help="registered project name")
    sp.add_argument("message", help="prompt text")
    sp.add_argument(
        "--quiet",
        action="store_true",
        help="suppress streaming text, only print the [done] line",
    )
    sp.set_defaults(func=_cmd_send)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
