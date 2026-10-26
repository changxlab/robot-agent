"""Edit the agent's operating rules (``CLAUDE.md`` in the project folder) from the web UI.

Claude Code reads CLAUDE.md when an agent process starts, so a saved change applies in each chat
from its next message (the session restarts the agent; see ``agent_context``). A save names the
version it was based on, so a change made meanwhile on disk (e.g. in an editor) is not silently
overwritten.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INSTRUCTIONS_FILE = "CLAUDE.md"
MAX_BYTES = 64_000


class InstructionsError(ValueError):
    """A request the UI should show as a clear message (empty, too large, conflict)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def path(project_dir: Path) -> Path:
    return project_dir / INSTRUCTIONS_FILE


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(project_dir: Path) -> str:
    """Hash of CLAUDE.md as it is on disk ("" when it does not exist)."""
    try:
        return _hash(path(project_dir).read_bytes())
    except OSError:
        return ""


def read(project_dir: Path) -> dict[str, Any]:
    file = path(project_dir)
    try:
        data = file.read_bytes()
        updated = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat()
    except FileNotFoundError:
        data, updated = b"", None
    return {"name": INSTRUCTIONS_FILE, "content": data.decode("utf-8", errors="replace"),
            "hash": _hash(data) if updated else "", "size": len(data), "updatedAt": updated}


def write(project_dir: Path, content: str, base_hash: str | None = None) -> dict[str, Any]:
    data = content.encode("utf-8")
    if not content.strip():
        raise InstructionsError(f"{INSTRUCTIONS_FILE} cannot be empty - the agent needs its "
                                "operating rules.")
    if len(data) > MAX_BYTES:
        raise InstructionsError(f"{INSTRUCTIONS_FILE} is larger than {MAX_BYTES // 1000} KB.")
    if base_hash is not None and base_hash != fingerprint(project_dir):
        raise InstructionsError(f"{INSTRUCTIONS_FILE} was changed by someone else since you "
                                "opened it. Reload it, then apply your edits again.", 409)
    file = path(project_dir)
    tmp = file.with_name(f".{file.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, file)
    return read(project_dir)
