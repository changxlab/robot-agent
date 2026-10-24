"""Tests of the on-disk chat and Claude transcript store."""

import asyncio

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.session_resume import materialize_resume_session
from claude_agent_sdk._internal.sessions import project_key_for_directory
from claude_agent_sdk.testing import run_session_store_conformance

from robot_agent.store import ChatStore, FileSessionStore

SESSION_ID = "3f2b8c1e-6a4d-4e0f-9b7a-1c2d3e4f5a6b"


def test_session_store_conformance(tmp_path):
    counter = iter(range(1000))
    asyncio.run(run_session_store_conformance(
        lambda: FileSessionStore(tmp_path / f"store{next(counter)}")))


def test_store_backed_resume_materializes_transcript(tmp_path):
    store = FileSessionStore(tmp_path / "transcripts")
    cwd = tmp_path / "project"
    cwd.mkdir()
    key = {"project_key": project_key_for_directory(str(cwd)), "session_id": SESSION_ID}
    entries = [{"type": "user", "uuid": "u1", "timestamp": "2026-01-01T00:00:00Z"},
               {"type": "assistant", "uuid": "a1", "timestamp": "2026-01-01T00:00:01Z"}]
    asyncio.run(store.append(key, entries))
    options = ClaudeAgentOptions(cwd=str(cwd), resume=SESSION_ID, session_store=store, env={})

    async def materialize():
        result = await materialize_resume_session(options)
        try:
            path = result.config_dir / "projects" / key["project_key"] / f"{SESSION_ID}.jsonl"
            return result.resume_session_id, path.read_text().count("\n")
        finally:
            await result.cleanup()

    assert asyncio.run(materialize()) == (SESSION_ID, 2)


def test_store_rejects_path_traversal(tmp_path):
    store = FileSessionStore(tmp_path)
    for key in ({"project_key": "..", "session_id": SESSION_ID},
                {"project_key": "p", "session_id": "../x"},
                {"project_key": "p", "session_id": SESSION_ID, "subpath": "../../etc"}):
        with pytest.raises(ValueError):
            asyncio.run(store.load(key))
    with pytest.raises(ValueError):
        ChatStore(tmp_path).save_meta("../evil", {})


def test_chat_store_round_trip_and_torn_line(tmp_path):
    chats = ChatStore(tmp_path)
    chats.save_meta("c1", {"id": "c1", "title": "t"})
    chats.append_event("c1", {"type": "user", "text": "hi"})
    with (tmp_path / "chats" / "c1" / "events.jsonl").open("a") as f:
        f.write('{"type": "assis')  # crash while writing
    assert chats.load_all() == [({"id": "c1", "title": "t"}, [{"type": "user", "text": "hi"}])]
