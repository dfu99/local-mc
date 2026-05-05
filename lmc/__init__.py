"""local-mc — local-first, chat-style desktop UI for Claude Code.

Public modules:
    config     — config paths and settings loading
    projects   — project registry (YAML)
    store      — SQLite chat & session storage
    sessions   — Claude subprocess manager
    artifacts  — artifact discovery and file watching
    server     — FastAPI web server
    cli        — `lmc` command-line entry point
"""

__version__ = "0.1.0"
