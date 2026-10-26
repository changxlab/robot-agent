"""End-to-end tests of the web server with a fake Claude SDK client.

The fake client imitates the Claude Code CLI: for each Bash tool call it runs the
PreToolUse hook and, when the hook answers "ask", the can_use_tool callback.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from fastapi.testclient import TestClient

import robot_agent.session as session_mod
import server
from robot_tools import config as robot_config

CAPTURE = Path(server.PROJECT_DIR) / "artifacts" / "captures" / "test_cam.jpg"
SCRIPT: dict[str, list[str]] = {}
SESSION_ID = "3f2b8c1e-6a4d-4e0f-9b7a-1c2d3e4f5a6b"


class FakeClient:
    instances = 0
    created: list["FakeClient"] = []
    fail_on: set[str] = set()
    # Prompts for which the fake imitates a gateway that repeats each tool call with an empty
    # input and then ends with Claude Code's synthetic stream-error message.
    duplicate_on: set[str] = set()

    def __init__(self, options):
        self.options = options
        self.prompt = ""
        self.interrupted = False
        FakeClient.instances += 1
        FakeClient.created.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        self.prompt = prompt

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        if self.prompt in FakeClient.fail_on:
            raise RuntimeError("Command failed with exit code 1")
        yield SystemMessage(subtype="init", data={"session_id": SESSION_ID, "model": "m"})
        hook = self.options.hooks["PreToolUse"][0].hooks[0]
        for i, command in enumerate(SCRIPT.get(self.prompt, []), start=1):
            tool_id = f"tool-{i}"
            yield AssistantMessage(content=[ToolUseBlock(id=tool_id, name="Bash",
                                                         input={"command": command})], model="m")
            if self.prompt in FakeClient.duplicate_on:
                yield AssistantMessage(content=[ToolUseBlock(id=tool_id, name="Bash", input={})],
                                       model="m")
            out = await hook({"tool_input": {"command": command}}, tool_id, {"signal": None})
            decision = out["hookSpecificOutput"]["permissionDecision"]
            if decision == "ask":
                perm = await self.options.can_use_tool(
                    "Bash", {"command": command}, ToolPermissionContext(tool_use_id=tool_id))
                decision = "allow" if isinstance(perm, PermissionResultAllow) else "deny"
            if decision == "allow":
                text = f"ran {command}\nIMAGE: artifacts/captures/{CAPTURE.name}"
                yield UserMessage(content=[ToolResultBlock(tool_use_id=tool_id, content=text)])
            else:
                yield UserMessage(content=[ToolResultBlock(tool_use_id=tool_id,
                                                           content="denied", is_error=True)])
            if self.prompt in FakeClient.duplicate_on:
                yield UserMessage(content=[ToolResultBlock(
                    tool_use_id=tool_id, is_error=True,
                    content="<tool_use_error>InputValidationError: Bash failed</tool_use_error>")])
        if self.prompt in FakeClient.duplicate_on:
            yield AssistantMessage(content=[TextBlock(text="API Error: Part of the response "
                                                      "never arrived.")], model="<synthetic>")
        yield AssistantMessage(content=[TextBlock(text=f"Finished: {self.prompt}")], model="m")
        yield ResultMessage(subtype="success", duration_ms=5, duration_api_ms=4, is_error=False,
                            num_turns=2, session_id=SESSION_ID)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(session_mod, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(server.settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(robot_config, "MODE_FILE", tmp_path / "run" / "mode")
    monkeypatch.delenv("ROBOT_MODE", raising=False)
    monkeypatch.delenv("ROBOT_MODE_LOCK", raising=False)
    robot_config.load.cache_clear()
    FakeClient.created.clear()
    FakeClient.fail_on.clear()
    FakeClient.duplicate_on.clear()
    server.sessions.clear()
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    CAPTURE.write_bytes(b"\xff\xd8\xff\xd9")
    with TestClient(server.app) as c:
        yield c
    CAPTURE.unlink(missing_ok=True)


def read_until(ws, kind, limit=60):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == kind:
            return msg, seen
    raise AssertionError(f"no {kind} in {[m['type'] for m in seen]}")


@contextmanager
def start_chat(client):
    chat = client.post("/api/chats").json()
    with client.websocket_connect("/ws") as ws:
        read_until(ws, "chats")
        ws.send_json({"type": "subscribe", "chatId": chat["id"]})
        read_until(ws, "history")
        yield chat, ws


def test_repeated_tool_calls_and_synthetic_errors_are_filtered(client):
    SCRIPT["dup"] = ["./robot status"]
    FakeClient.duplicate_on.add("dup")
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "dup"})
        _, seen = read_until(ws, "done")
        uses = [m for m in seen if m["type"] == "tool_use"]
        assert [u["input"] for u in uses] == [{"command": "./robot status"}]
        results = [m for m in seen if m["type"] == "tool_result"]
        assert len(results) == 1 and results[0]["isError"] is False
        assert any(m["type"] == "error" and m["text"].startswith("API Error") for m in seen)
        assert not any(m["type"] == "assistant" and "API Error" in m["text"] for m in seen)


def test_read_only_command_runs_without_approval(client):
    SCRIPT["check"] = ["./robot status"]
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "check"})
        done, seen = read_until(ws, "done")
        types = [m["type"] for m in seen]
        assert "approval_request" not in types
        safety = next(m for m in seen if m["type"] == "safety")
        assert safety["action"] == "allow"
        result = next(m for m in seen if m["type"] == "tool_result")
        assert result["images"] == [f"/artifacts/captures/{CAPTURE.name}"]
        assert [(m["url"], m["kind"]) for m in result["media"]] == [
            (f"/artifacts/captures/{CAPTURE.name}", "image")]
        assert any(m["type"] == "assistant" and m["text"] == "Finished: check" for m in seen)
        assert done["ok"] is True
        assert client.get(result["images"][0]).status_code == 200


def test_motion_waits_for_operator_approval(client):
    SCRIPT["walk"] = ["./robot base move --vx 0.2 --duration 1"]
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "walk"})
        req, _ = read_until(ws, "approval_request")
        assert req["category"] == "motion" and req["command"].startswith("./robot base move")
        ws.send_json({"type": "approval", "chatId": chat["id"], "id": req["id"], "approve": True})
        res, _ = read_until(ws, "approval_result")
        assert res["approved"] is True
        _, seen = read_until(ws, "done")
        assert any(m["type"] == "tool_result" and not m["isError"] for m in seen)


def test_declined_motion_is_reported_to_agent(client):
    SCRIPT["arm"] = ["./robot arm home"]
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "arm"})
        req, _ = read_until(ws, "approval_request")
        ws.send_json({"type": "approval", "chatId": chat["id"], "id": req["id"], "approve": False,
                      "note": "people nearby"})
        res, _ = read_until(ws, "approval_result")
        assert res == {**res, "approved": False, "note": "people nearby"}
        _, seen = read_until(ws, "done")
        assert any(m["type"] == "tool_result" and m["isError"] for m in seen)


def test_dangerous_command_blocked_without_asking(client):
    SCRIPT["bad"] = ["sudo reboot"]
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "bad"})
        _, seen = read_until(ws, "done")
        assert "approval_request" not in [m["type"] for m in seen]
        assert next(m for m in seen if m["type"] == "safety")["action"] == "deny"


def test_history_replay_and_chat_listing(client):
    SCRIPT["hello"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "hello"})
        read_until(ws, "done")
        detail = client.get(f"/api/chats/{chat['id']}").json()
        assert detail["title"] == "hello"
        assert [e["type"] for e in detail["events"]][:1] == ["user"]
        assert client.get("/api/chats").json()[0]["id"] == chat["id"]
        assert client.delete(f"/api/chats/{chat['id']}").json() == {"ok": True}
        assert client.get(f"/api/chats/{chat['id']}").status_code == 404


def test_estop_runs_hardware_stop_and_broadcasts(client, monkeypatch):
    calls = []

    async def fake_run(*args, timeout):
        calls.append(args)
        return 0, "B2: stop-move sent"

    monkeypatch.setattr(server, "run_robot", fake_run)
    with start_chat(client) as (_, ws):
        ws.send_json({"type": "estop"})
        msg, _ = read_until(ws, "estop")
        assert msg["ok"] is True and ("estop",) in calls
        assert client.post("/api/estop").json()["ok"] is True


def test_artifact_paths_are_restricted(client):
    assert client.get("/artifacts/logs/server.log").status_code == 404
    assert client.get("/artifacts/captures/..%2Frobot.yaml").status_code == 404
    assert client.get("/artifacts/videos/clip.exe").status_code == 404


@pytest.fixture()
def media_files():
    root = Path(server.PROJECT_DIR) / "artifacts"
    files = {"videos/test_clip.mp4": bytes(range(256)) * 4,
             "pointclouds/test_cloud.pcd": b"# .PCD v0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
             b"COUNT 1 1 1\nWIDTH 1\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 1\nDATA ascii\n1 2 3\n"}
    created_dirs = [root / d for d in ("videos", "pointclouds") if not (root / d).exists()]
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    yield {rel: root / rel for rel in files}
    for rel in files:
        (root / rel).unlink(missing_ok=True)
    for d in created_dirs:
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()


def test_video_and_point_cloud_artifacts_are_served(client, media_files):
    video = client.get("/artifacts/videos/test_clip.mp4", headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100
    assert video.headers["content-type"] == "video/mp4"
    assert client.get("/artifacts/pointclouds/test_cloud.pcd").content.startswith(b"# .PCD")
    listed = {m["url"]: m for m in client.get("/api/artifacts").json()}
    assert listed["/artifacts/videos/test_clip.mp4"]["kind"] == "video"
    assert listed["/artifacts/pointclouds/test_cloud.pcd"]["kind"] == "pointcloud"
    assert listed[f"/artifacts/captures/{CAPTURE.name}"]["kind"] == "image"
    assert client.get("/static/vendor/three/three.module.min.js").status_code == 200
    assert client.get("/static/pointcloud-viewer.js").status_code == 200


def test_tool_output_media_lines_are_parsed(client, media_files):
    from robot_agent.media import media_in_output

    text = (f"IMAGE: artifacts/captures/{CAPTURE.name}\nVIDEO: artifacts/videos/test_clip.mp4\n"
            "POINTCLOUD: artifacts/pointclouds/test_cloud.pcd\nVIDEO: artifacts/videos/missing.mp4\n"
            "IMAGE: artifacts/logs/server.log\n  IMAGE: artifacts/captures/../robot.yaml")
    found = media_in_output(text, Path(server.PROJECT_DIR))
    assert [(m["url"], m["kind"]) for m in found] == [
        (f"/artifacts/captures/{CAPTURE.name}", "image"),
        ("/artifacts/videos/test_clip.mp4", "video"),
        ("/artifacts/pointclouds/test_cloud.pcd", "pointcloud"),
    ]


def test_access_token(client, monkeypatch):
    monkeypatch.setattr(server.settings, "access_token", "secret")
    assert client.get("/api/chats").status_code == 401
    assert client.get("/api/chats?token=secret").status_code == 200
    assert client.get("/api/chats", headers={"X-Robot-Token": "secret"}).status_code == 200
    assert client.get("/").status_code == 200


def test_chats_are_saved_and_restored_after_restart(client):
    SCRIPT["remember"] = ["./robot status"]
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "remember"})
        read_until(ws, "done")
    before = client.get(f"/api/chats/{chat['id']}").json()
    assert FakeClient.created[-1].options.resume is None
    saved = server.settings.sessions_dir / "chats" / chat["id"]
    assert (saved / "chat.json").is_file() and (saved / "events.jsonl").is_file()

    server.sessions.clear()
    with TestClient(server.app) as c:
        after = c.get(f"/api/chats/{chat['id']}").json()
        assert after["title"] == "remember"
        assert after["events"] == before["events"]
        assert server.sessions[chat["id"]].claude_session_id == SESSION_ID

        SCRIPT["again"] = []
        with start_chat_ws(c, chat["id"]) as ws:
            ws.send_json({"type": "chat", "chatId": chat["id"], "content": "again"})
            read_until(ws, "done")
        options = FakeClient.created[-1].options
        assert options.resume == SESSION_ID
        assert options.session_store is server.chat_store.transcripts


def test_interrupted_turn_is_closed_on_restore(client):
    chat = client.post("/api/chats").json()
    store = server.chat_store
    store.append_event(chat["id"], {"type": "user", "text": "walk", "chatId": chat["id"],
                                    "ts": "2026-01-01T00:00:00+00:00"})
    server.sessions.clear()
    with TestClient(server.app) as c:
        events = c.get(f"/api/chats/{chat['id']}").json()["events"]
        assert [e["type"] for e in events] == ["user", "error", "done"]
        assert server.sessions[chat["id"]].busy is False


def test_failed_resume_starts_fresh_context(client):
    SCRIPT["first"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "first"})
        read_until(ws, "done")
    server.sessions.clear()
    with TestClient(server.app) as c:
        FakeClient.fail_on.add("second")
        with start_chat_ws(c, chat["id"]) as ws:
            ws.send_json({"type": "chat", "chatId": chat["id"], "content": "second"})
            _, seen = read_until(ws, "done")
            assert any("previous context" in m.get("text", "") for m in seen)
            assert server.sessions[chat["id"]].claude_session_id is None
            # The broken agent process is replaced on the next message.
            SCRIPT["third"] = []
            ws.send_json({"type": "chat", "chatId": chat["id"], "content": "third"})
            done, _ = read_until(ws, "done")
            assert done["ok"] is True
            assert FakeClient.created[-1].options.resume is None


def test_delete_removes_saved_chat(client):
    SCRIPT["bye"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "bye"})
        read_until(ws, "done")
    transcripts = server.chat_store.transcripts
    key = {"project_key": "proj", "session_id": SESSION_ID}
    import asyncio
    asyncio.run(transcripts.append(key, [{"type": "user", "uuid": "u1"}]))
    assert client.delete(f"/api/chats/{chat['id']}").json() == {"ok": True}
    assert not (server.settings.sessions_dir / "chats" / chat["id"]).exists()
    assert asyncio.run(transcripts.load(key)) is None
    server.sessions.clear()
    with TestClient(server.app) as c:
        assert c.get("/api/chats").json() == []



def test_mode_switch_updates_tools_and_tells_agent(client):
    start = client.get("/api/config").json()["mode"]
    other = "sim" if start == "real" else "real"
    SCRIPT["before"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "before"})
        read_until(ws, "done")
        assert client.post("/api/mode", json={"mode": other}).json()["mode"] == other
        event, _ = read_until(ws, "mode")
        assert event["chatId"] == chat["id"] and event["mode"] == other
        broadcast, _ = read_until(ws, "mode")
        assert "chatId" not in broadcast and broadcast["mode"] == other
        assert robot_config.MODE_FILE.read_text().strip() == other
        assert robot_config.load()["mode"] == other

        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "after"})
        read_until(ws, "done")
        prompt = FakeClient.created[-1].prompt
        assert prompt.startswith("[Operator note: robot mode switched") and prompt.endswith("after")
        # The note is sent once.
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "later"})
        read_until(ws, "done")
        assert FakeClient.created[-1].prompt == "later"
    assert client.get("/api/config").json()["mode"] == other


def test_mode_switch_refused_while_agent_works(client):
    chat = client.post("/api/chats").json()
    server.sessions[chat["id"]].busy = True
    res = client.post("/api/mode", json={"mode": "sim"})
    assert res.status_code == 409
    assert not robot_config.MODE_FILE.exists()
    server.sessions[chat["id"]].busy = False
    assert client.post("/api/mode", json={"mode": "bogus"}).status_code == 422


def test_startup_robot_mode_env_becomes_switchable(client, monkeypatch):
    monkeypatch.setenv("ROBOT_MODE", "sim")
    server.init_mode()
    # Agent processes inherit the server environment, so ROBOT_MODE must not stay there.
    import os
    assert "ROBOT_MODE" not in os.environ
    assert client.get("/api/config").json()["mode"] == "sim"
    assert client.post("/api/mode", json={"mode": "real"}).json()["mode"] == "real"


def test_locked_mode_cannot_be_switched(client, monkeypatch):
    monkeypatch.setenv("ROBOT_MODE_LOCK", "sim")
    robot_config.set_mode("real")
    config = client.get("/api/config").json()
    assert config["mode"] == "sim" and config["modeLocked"] is True
    res = client.post("/api/mode", json={"mode": "real"})
    assert res.status_code == 403
    assert robot_config.load()["mode"] == "sim"
    assert client.post("/api/mode", json={"mode": "sim"}).status_code == 200


def test_mode_event_does_not_mark_turn_interrupted_on_restore(client):
    SCRIPT["hi"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "hi"})
        read_until(ws, "done")
    client.post("/api/mode", json={"mode": "sim"})
    server.sessions.clear()
    with TestClient(server.app) as c:
        events = c.get(f"/api/chats/{chat['id']}").json()["events"]
        assert [e["type"] for e in events][-2:] == ["done", "mode"]
        assert not any(e["type"] == "error" for e in events)

@contextmanager
def start_chat_ws(client, chat_id):
    with client.websocket_connect("/ws") as ws:
        read_until(ws, "chats")
        ws.send_json({"type": "subscribe", "chatId": chat_id})
        read_until(ws, "history")
        yield ws


def skill_md(name, description="Use it."):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


@pytest.fixture()
def skills_dir(monkeypatch, tmp_path):
    project = tmp_path / "project"
    for name in ("piper-arm", "robot-status"):
        (project / ".claude" / "skills" / name).mkdir(parents=True)
        (project / ".claude" / "skills" / name / "SKILL.md").write_text(skill_md(name))
    monkeypatch.setattr(server.settings, "project_dir", project)
    return project


def test_suggestions_are_saved_per_language_and_broadcast(client):
    assert client.get("/api/suggestions").json() == {"custom": {}}
    items = [{"label": "Teach", "text": "Record a trajectory"}]
    with client.websocket_connect("/ws") as ws:
        read_until(ws, "chats")
        assert client.put("/api/suggestions/en", json={"items": items}).json() == {
            "custom": {"en": items}}
        msg, _ = read_until(ws, "suggestions")
        assert msg["custom"] == {"en": items}
    assert client.get("/api/suggestions").json() == {"custom": {"en": items}}
    assert client.put("/api/suggestions/zh", json={"items": []}).json()["custom"]["zh"] == []
    assert client.delete("/api/suggestions/en").json() == {"custom": {"zh": []}}
    assert client.put("/api/suggestions/fr", json={"items": []}).status_code == 404
    bad = [{"label": " ", "text": "x"}]
    assert client.put("/api/suggestions/en", json={"items": bad}).status_code == 422
    assert client.put("/api/suggestions/en",
                      json={"items": [{"label": "x" * 41, "text": "y"}]}).status_code == 422
    assert client.put("/api/suggestions/en",
                      json={"items": [{"label": "a", "text": "b"}] * 25}).status_code == 422


def test_skills_can_be_listed_edited_created_disabled_and_deleted(client, skills_dir):
    names = [s["name"] for s in client.get("/api/skills").json()]
    assert names == ["piper-arm", "robot-status"]
    skill = client.get("/api/skills/piper-arm").json()
    assert skill["enabled"] is True and skill["description"] == "Use it."

    updated = skill_md("piper-arm", "Arm control.")
    assert client.put("/api/skills/piper-arm", json={"content": updated}).json()["content"] == updated
    assert client.put("/api/skills/piper-arm",
                      json={"content": skill_md("other")}).status_code == 400
    assert client.put("/api/skills/piper-arm", json={"content": "no front matter"}).status_code == 400

    new = skill_md("weed-check", "Inspect weeds.")
    assert client.post("/api/skills", json={"name": "weed-check", "content": new}).status_code == 201
    assert client.post("/api/skills", json={"name": "weed-check", "content": new}).status_code == 409
    assert client.post("/api/skills", json={"name": "../evil", "content": new}).status_code == 400
    assert client.get("/api/skills/..%2Fsecrets").status_code in (400, 404)

    off = client.patch("/api/skills/weed-check", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert (skills_dir / ".claude" / "skills-disabled" / "weed-check" / "SKILL.md").is_file()
    assert not (skills_dir / ".claude" / "skills" / "weed-check").exists()
    assert {s["name"]: s["enabled"] for s in client.get("/api/skills").json()}["weed-check"] is False
    assert client.patch("/api/skills/weed-check", json={"enabled": True}).json()["enabled"] is True

    assert client.delete("/api/skills/weed-check").json() == {"ok": True}
    assert client.get("/api/skills/weed-check").status_code == 404


def test_skill_changes_restart_the_agent_with_its_context(client, skills_dir):
    SCRIPT["one"] = []
    SCRIPT["two"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "one"})
        read_until(ws, "done")
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "one"})
        read_until(ws, "done")
        assert len(FakeClient.created) == 1
        assert FakeClient.created[-1].options.skills == ["piper-arm", "robot-status"]
        client.patch("/api/skills/robot-status", json={"enabled": False})
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "two"})
        read_until(ws, "done")
    restarted = FakeClient.created[-1]
    assert len(FakeClient.created) == 2
    assert restarted.options.skills == ["piper-arm"]
    assert restarted.options.resume == SESSION_ID


@pytest.fixture()
def fake_cli(monkeypatch, tmp_path):
    """A stand-in for ./robot: `arm take-control` succeeds, or hangs while FAKE_HANG is set."""
    script = tmp_path / "robot"
    script.write_text("""#!/bin/bash
echo "$@" >> "$(dirname "$0")/calls.log"
case "$1 $2" in
  "arm take-control")
    echo "arm: standby mode, emergency stop - emergency-stopping it until joints 2, 3 and 5 settle"
    if [ -n "$FAKE_HANG" ]; then exec sleep 30; fi
    echo "arm: in CAN command mode and enabled";;
  "estop "*|"estop ") echo "B2: stop-move sent"; echo "arm: emergency stop sent";;
  *) echo '{"summary": {"ok": true, "issues": []}}';;
esac
""")
    script.chmod(0o755)
    monkeypatch.setattr(server, "ROBOT_CLI", script)
    return tmp_path / "calls.log"


def test_recover_runs_take_control_and_broadcasts(client, fake_cli):
    with client.websocket_connect("/ws") as ws:
        read_until(ws, "chats")
        res = client.post("/api/recover").json()
        assert res["ok"] is True and "CAN command mode" in res["output"]
        msg, _ = read_until(ws, "recover")
        assert msg["ok"] is True
    assert "arm take-control --settle-wait 60" in fake_cli.read_text()


def test_recover_refused_while_an_agent_works(client, fake_cli):
    chat = client.post("/api/chats").json()
    server.sessions[chat["id"]].busy = True
    try:
        res = client.post("/api/recover")
        assert res.status_code == 409 and "agent" in res.json()["detail"]
    finally:
        server.sessions[chat["id"]].busy = False
    assert not fake_cli.exists()


def test_estop_cancels_a_running_recovery(client, fake_cli, monkeypatch):
    import threading
    import time

    monkeypatch.setenv("FAKE_HANG", "1")
    result = {}
    worker = threading.Thread(target=lambda: result.update(r=client.post("/api/recover")))
    worker.start()
    for _ in range(100):
        if server._recovery["proc"] is not None:
            break
        time.sleep(0.05)
    assert server._recovery["proc"] is not None
    assert client.post("/api/recover").status_code == 409  # only one at a time
    started = time.monotonic()
    assert client.post("/api/estop").json()["ok"] is True
    worker.join(10)
    assert not worker.is_alive() and time.monotonic() - started < 5
    body = result["r"].json()
    assert body["ok"] is False and "Cancelled by E-STOP" in body["output"]
    assert server._recovery["proc"] is None


def test_claude_md_can_be_read_and_saved(client, skills_dir):
    (skills_dir / "CLAUDE.md").write_text("# Robot operator agent\n\nOld rules.\n")
    doc = client.get("/api/instructions").json()
    assert doc["name"] == "CLAUDE.md" and doc["content"].endswith("Old rules.\n")
    assert doc["hash"] and doc["size"] == len(doc["content"].encode())

    new = "# Robot operator agent\n\nYou work on a TCM farm in Wuxi.\n"
    saved = client.put("/api/instructions", json={"content": new, "baseHash": doc["hash"]}).json()
    assert saved["content"] == new and saved["hash"] != doc["hash"]
    assert (skills_dir / "CLAUDE.md").read_text() == new

    # Saving over a version that changed meanwhile (e.g. in an editor) is refused.
    stale = client.put("/api/instructions", json={"content": "mine", "baseHash": doc["hash"]})
    assert stale.status_code == 409 and "changed by someone else" in stale.json()["detail"]
    assert (skills_dir / "CLAUDE.md").read_text() == new
    assert client.put("/api/instructions",
                      json={"content": "  \n", "baseHash": saved["hash"]}).status_code == 400
    assert client.put("/api/instructions",
                      json={"content": "x" * 70_000, "baseHash": saved["hash"]}).status_code == 400
    assert not list(skills_dir.glob(".CLAUDE.md*"))  # no temp file left behind


def test_claude_md_changes_restart_the_agent_with_its_context(client, skills_dir):
    (skills_dir / "CLAUDE.md").write_text("# Rules v1\n")
    SCRIPT["one"] = []
    SCRIPT["two"] = []
    with start_chat(client) as (chat, ws):
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "one"})
        read_until(ws, "done")
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "one"})
        read_until(ws, "done")
        assert len(FakeClient.created) == 1
        doc = client.get("/api/instructions").json()
        client.put("/api/instructions", json={"content": "# Rules v2\n", "baseHash": doc["hash"]})
        ws.send_json({"type": "chat", "chatId": chat["id"], "content": "two"})
        read_until(ws, "done")
    assert len(FakeClient.created) == 2
    assert FakeClient.created[-1].options.resume == SESSION_ID
