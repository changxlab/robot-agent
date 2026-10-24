"""On-disk persistence for chats, under the project's ``.claude/sessions/`` folder.

Layout::

    .claude/sessions/
      chats/<chat-id>/chat.json          title, timestamps, Claude session id
      chats/<chat-id>/events.jsonl       UI event history (one JSON object per line)
      transcripts/<project-key>/<session-id>.jsonl            Claude Code transcript
      transcripts/<project-key>/<session-id>/<subpath>.jsonl  subagent transcripts

Transcripts are written through the SDK's ``session_store`` mirror, so a chat can resume
its agent context after the server restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("robot_agent")

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")


def _safe(name: str) -> str:
    if not _SAFE_NAME.fullmatch(name) or name == "." or ".." in name:
        raise ValueError(f"unsafe storage name: {name!r}")
    return name


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _read_jsonl(path: Path) -> list[Any]:
    entries = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:  # a torn last line after a crash
                logger.warning("skipping corrupt line in %s", path)
    return entries


class FileSessionStore:
    """``claude_agent_sdk.SessionStore`` that keeps transcripts as local JSONL files."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = asyncio.Lock()

    def _path(self, key: dict[str, Any]) -> Path:
        session_dir = self.root / _safe(key["project_key"])
        session_id = _safe(key["session_id"])
        subpath = key.get("subpath")
        if not subpath:
            return session_dir / f"{session_id}.jsonl"
        parts = [_safe(p) for p in subpath.split("/")]
        return session_dir.joinpath(session_id, *parts[:-1], parts[-1] + ".jsonl")

    async def append(self, key: dict[str, Any], entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        path = self._path(key)
        data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        async with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(data)

    async def load(self, key: dict[str, Any]) -> list[dict[str, Any]] | None:
        path = self._path(key)
        return _read_jsonl(path) if path.is_file() else None

    async def list_sessions(self, project_key: str) -> list[dict[str, Any]]:
        project_dir = self.root / _safe(project_key)
        if not project_dir.is_dir():
            return []
        return [{"session_id": p.stem, "mtime": int(p.stat().st_mtime * 1000)}
                for p in project_dir.glob("*.jsonl")]

    async def delete(self, key: dict[str, Any]) -> None:
        path = self._path(key)
        async with self._lock:
            path.unlink(missing_ok=True)
            if not key.get("subpath"):
                shutil.rmtree(path.with_suffix(""), ignore_errors=True)

    async def list_subkeys(self, key: dict[str, Any]) -> list[str]:
        session_dir = self.root / _safe(key["project_key"]) / _safe(key["session_id"])
        if not session_dir.is_dir():
            return []
        return [p.relative_to(session_dir).with_suffix("").as_posix()
                for p in session_dir.rglob("*.jsonl")]

    async def delete_session(self, session_id: str) -> None:
        """Delete a transcript (and its subagent transcripts) in every project key."""
        if not self.root.is_dir():
            return
        for project_dir in self.root.iterdir():
            if project_dir.is_dir():
                await self.delete({"project_key": project_dir.name, "session_id": session_id})


class ChatStore:
    """Chat metadata and UI event history, plus the Claude transcript store."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.chats_dir = self.root / "chats"
        self.transcripts = FileSessionStore(self.root / "transcripts")

    def _chat_dir(self, chat_id: str) -> Path:
        return self.chats_dir / _safe(chat_id)

    def save_meta(self, chat_id: str, meta: dict[str, Any]) -> None:
        try:
            _write_json_atomic(self._chat_dir(chat_id) / "chat.json", meta)
        except OSError:
            logger.exception("could not save chat %s", chat_id)

    def append_event(self, chat_id: str, event: dict[str, Any]) -> None:
        path = self._chat_dir(chat_id) / "events.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.exception("could not save event for chat %s", chat_id)

    def load_all(self) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """(metadata, events) for every saved chat; unreadable chats are skipped."""
        chats = []
        if not self.chats_dir.is_dir():
            return chats
        for chat_dir in sorted(self.chats_dir.iterdir()):
            meta_path = chat_dir / "chat.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                events_path = chat_dir / "events.jsonl"
                events = _read_jsonl(events_path) if events_path.is_file() else []
            except (OSError, ValueError):
                logger.exception("could not load chat from %s", chat_dir)
                continue
            if meta.get("id") == chat_dir.name:
                chats.append((meta, events))
        return chats

    async def delete(self, chat_id: str, claude_session_id: str | None = None) -> None:
        shutil.rmtree(self._chat_dir(chat_id), ignore_errors=True)
        if claude_session_id:
            await self.transcripts.delete_session(claude_session_id)
