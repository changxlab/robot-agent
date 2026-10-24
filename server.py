"""Robot agent web server: chat with a Claude agent that operates the robot.

REST:
  GET    /api/config               mode, model, approval timeout
  POST   /api/mode                 switch the robot mode {mode: "sim"|"real"} (not while an agent works)
  GET    /api/chats                list chats
  POST   /api/chats                create a chat
  GET    /api/chats/{id}           chat summary and event history
  DELETE /api/chats/{id}           delete a chat (and its saved files)
  GET    /api/robot/status         `./robot status --json` (cached for a few seconds)
  POST   /api/estop                stop all actuators and interrupt every agent turn
  POST   /api/recover              recover the arm after an emergency stop (`./robot arm take-control`)
  GET    /api/artifacts            media files under artifacts/ (newest first)
  GET    /api/suggestions          custom welcome-screen prompts per UI language
  PUT    /api/suggestions/{lang}   save the prompts for a language {items: [{label, text}]}
  DELETE /api/suggestions/{lang}   back to the built-in prompts for a language
  GET    /api/skills               robot skills (.claude/skills, disabled ones included)
  POST   /api/skills               create a skill {name, content}
  GET    /api/skills/{name}        a skill with its SKILL.md content
  PUT    /api/skills/{name}        save SKILL.md {content}
  PATCH  /api/skills/{name}        enable or disable a skill {enabled}
  DELETE /api/skills/{name}        delete a skill folder
  GET    /artifacts/{captures|maps|videos|pointclouds}/{file}
                                   images, mp4/webm video (Range supported), pcd/ply point clouds
  GET    /static/...               front-end libraries (three.js)

WebSocket /ws (JSON messages):
  client -> server: subscribe {chatId} | chat {chatId, content} | approval {chatId, id, approve, note}
                    | interrupt {chatId} | estop
  server -> client: chat events (user, assistant, tool_use, safety, tool_result, approval_request,
                    approval_result, init, result, error, done, mode), history, chats, estop,
                    mode, notice, suggestions, recover

Chats are saved under .claude/sessions/ (ROBOT_SESSIONS_DIR) and restored on startup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from robot_agent import skills as skill_files
from robot_agent.config import PROJECT_DIR, Settings
from robot_agent.media import ARTIFACT_DIRS, kind_of, list_media
from robot_agent.session import ChatSession
from robot_agent.store import ChatStore
from robot_agent.suggestions import LANGS, MAX_ITEMS, MAX_LABEL, MAX_TEXT, SuggestionStore
from robot_tools import config as robot_config

ROBOT_CLI = PROJECT_DIR / "robot"
STATUS_CACHE_SECONDS = 8.0

settings = Settings()
sessions: dict[str, ChatSession] = {}
chat_store: ChatStore | None = None
logger = logging.getLogger("robot_agent")


def setup_logging() -> None:
    log_dir = PROJECT_DIR / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "server.log", maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class Connection:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.chat_id: str | None = None
        self._lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any]) -> bool:
        try:
            async with self._lock:
                await self.ws.send_text(json.dumps(payload, default=str))
            return True
        except Exception:
            return False


connections: set[Connection] = set()


async def broadcast_all(payload: dict[str, Any]) -> None:
    for c in list(connections):
        if not await c.send(payload):
            connections.discard(c)


async def broadcast_chat(chat_id: str, event: dict[str, Any]) -> None:
    for c in [c for c in list(connections) if c.chat_id == chat_id]:
        if not await c.send(event):
            connections.discard(c)
    if event["type"] in ("user", "done"):
        await broadcast_all({"type": "chats", "chats": chat_list()})


def chat_list() -> list[dict[str, Any]]:
    return [s.summary() for s in sorted(sessions.values(), key=lambda s: s.updated_at,
                                        reverse=True)]


def get_session(chat_id: str) -> ChatSession:
    session = sessions.get(chat_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return session


def token_ok(token: str | None) -> bool:
    return not settings.access_token or (
        token is not None and secrets.compare_digest(token, settings.access_token))


def require_token(request: Request) -> None:
    token = request.headers.get("x-robot-token") or request.query_params.get("token")
    if not token_ok(token):
        raise HTTPException(status_code=401, detail="Missing or invalid access token")


def load_chats() -> None:
    global chat_store
    chat_store = ChatStore(settings.sessions_dir)
    for meta, events in chat_store.load_all():
        sessions[meta["id"]] = ChatSession.restore(settings, broadcast_chat, chat_store, meta,
                                                   events)
    logger.info("restored %d chat(s) from %s", len(sessions), settings.sessions_dir)


def init_mode() -> None:
    # Agent processes inherit this server's environment, and ROBOT_MODE would override the mode
    # chosen in the UI, so move a startup ROBOT_MODE into the runtime mode file instead.
    env_mode = os.environ.pop("ROBOT_MODE", "").strip()
    if env_mode:
        robot_config.set_mode(env_mode)


def current_mode() -> str:
    robot_config.load.cache_clear()  # the mode file may have changed since the last read
    try:
        return robot_config.load()["mode"]
    except Exception as exc:  # a malformed robot.yaml should not break the UI
        return f"unknown ({exc})"


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    init_mode()
    logger.info("robot agent server started (model %s, mode %s)", settings.model, current_mode())
    load_chats()
    yield
    await asyncio.gather(*(s.close() for s in sessions.values()), return_exceptions=True)


app = FastAPI(lifespan=lifespan)
api = [Depends(require_token)]
# Front-end libraries (three.js); public, like index.html.
app.mount("/static", StaticFiles(directory=PROJECT_DIR / "static"), name="static")


# ----- robot CLI -----

async def run_robot(*args: str, timeout: float, on_start=None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        str(ROBOT_CLI), *args, cwd=str(PROJECT_DIR),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    if on_start is not None:
        on_start(proc)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"./robot {' '.join(args)} timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode(errors="replace")


_status_cache: dict[str, Any] = {"at": 0.0, "data": None}
_status_lock = asyncio.Lock()


async def robot_status() -> dict[str, Any]:
    async with _status_lock:
        cached = _status_cache["data"]
        if (cached and time.monotonic() - _status_cache["at"] < STATUS_CACHE_SECONDS
                and cached.get("mode") == current_mode()):
            return cached
        code, out = await run_robot("status", "--json", timeout=40)
        try:
            data = json.loads(out[out.index("{"):])
        except ValueError:
            data = {"error": out.strip()[-500:] or f"exit code {code}"}
        _status_cache.update(at=time.monotonic(), data=data)
        return data


async def emergency_stop(source: str) -> dict[str, Any]:
    logger.warning("EMERGENCY STOP requested from %s", source)
    # A recovery in progress would clear the new stop once the arm settles: kill it first.
    cancel_recovery()
    # Send the hardware stop first; interrupting the agent must not delay it.
    hardware = asyncio.create_task(run_robot("estop", timeout=20))
    await asyncio.gather(*(s.interrupt("Emergency stop") for s in sessions.values()),
                         return_exceptions=True)
    code, out = await hardware
    result = {"type": "estop", "ok": code == 0, "output": out.strip(), "source": source}
    logger.warning("emergency stop result (exit %s): %s", code, out.strip())
    _status_cache["at"] = 0.0
    await broadcast_all(result)
    return result


# Arm recovery after an emergency stop. The arm sinks to its rest pose before the stop is
# cleared, so this can take up to RECOVER_SETTLE_S.
RECOVER_SETTLE_S = 60
_recovery: dict[str, Any] = {"proc": None, "cancelled": False}


def cancel_recovery() -> bool:
    proc = _recovery["proc"]
    if proc is None or proc.returncode is not None:
        return False
    _recovery["cancelled"] = True
    proc.kill()
    logger.warning("arm recovery cancelled by an emergency stop")
    return True


async def recover_arm(source: str) -> dict[str, Any]:
    if _recovery["proc"] is not None:
        raise HTTPException(status_code=409, detail="An arm recovery is already running.")
    if any(s.busy for s in sessions.values()):
        raise HTTPException(status_code=409, detail="An agent is working. Stop it before "
                            "recovering the arm, so it does not move the arm at the same time.")
    logger.warning("arm recovery (take-control) requested from %s", source)
    _recovery.update(cancelled=False)

    def started(proc) -> None:
        _recovery["proc"] = proc

    try:
        code, out = await run_robot("arm", "take-control", "--settle-wait", str(RECOVER_SETTLE_S),
                                    timeout=RECOVER_SETTLE_S + 30, on_start=started)
    finally:
        _recovery["proc"] = None
    cancelled = _recovery["cancelled"]
    output = "Cancelled by E-STOP; the arm stays emergency-stopped." if cancelled else out.strip()
    result = {"type": "recover", "ok": code == 0 and not cancelled, "output": output,
              "source": source}
    logger.warning("arm recovery result (exit %s): %s", code, output)
    _status_cache["at"] = 0.0
    await broadcast_all(result)
    return result


# ----- HTTP routes -----

@app.get("/")
def index():
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/api/config", dependencies=api)
def get_config():
    return {"mode": current_mode(), "modeLocked": robot_config.locked_mode() is not None,
            "model": settings.model, "approvalTimeout": settings.approval_timeout}


class ModeRequest(BaseModel):
    mode: Literal["real", "sim"]


@app.post("/api/mode", dependencies=api)
async def post_mode(req: ModeRequest):
    locked = robot_config.locked_mode()
    if locked and req.mode != locked:
        raise HTTPException(status_code=403, detail=f"This server is locked to {locked} mode "
                            "(ROBOT_MODE_LOCK).")
    if any(s.busy for s in sessions.values()):
        raise HTTPException(status_code=409, detail="An agent is still working. Wait for it to "
                            "finish or stop it before switching the robot mode.")
    if current_mode() != req.mode:
        robot_config.set_mode(req.mode)
        _status_cache.update(at=0.0, data=None)
        logger.warning("robot mode switched to %s from the web UI", req.mode)
        await asyncio.gather(*(s.mode_changed(req.mode) for s in sessions.values()))
        await broadcast_all({"type": "mode", "mode": req.mode})
    return get_config()


@app.get("/api/chats", dependencies=api)
def list_chats():
    return chat_list()


@app.post("/api/chats", status_code=201, dependencies=api)
def create_chat():
    session = ChatSession(settings, broadcast_chat, chat_store)
    sessions[session.id] = session
    return session.summary()


@app.get("/api/chats/{chat_id}", dependencies=api)
def get_chat(chat_id: str):
    session = get_session(chat_id)
    return {**session.summary(), "events": session.events}


@app.delete("/api/chats/{chat_id}", dependencies=api)
async def delete_chat(chat_id: str):
    session = get_session(chat_id)
    if session.busy:
        raise HTTPException(status_code=409, detail="Stop the agent before deleting this chat")
    del sessions[chat_id]
    await session.close()
    if chat_store is not None:
        await chat_store.delete(chat_id, session.claude_session_id)
    await broadcast_all({"type": "chats", "chats": chat_list()})
    return {"ok": True}


@app.get("/api/robot/status", dependencies=api)
async def get_robot_status():
    return await robot_status()


@app.post("/api/estop", dependencies=api)
async def post_estop():
    return await emergency_stop("http")


@app.post("/api/recover", dependencies=api)
async def post_recover():
    return await recover_arm("http")


@app.get("/api/artifacts", dependencies=api)
def get_artifacts():
    return list_media(PROJECT_DIR)


@app.get("/artifacts/{kind}/{name}", dependencies=api)
def get_artifact(kind: str, name: str):
    if kind not in ARTIFACT_DIRS or not kind_of(name):
        raise HTTPException(status_code=404)
    path = PROJECT_DIR / "artifacts" / kind / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    # FileResponse answers HTTP Range requests, so videos can seek.
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


# ----- suggested prompts -----

def suggestion_store() -> SuggestionStore:
    return SuggestionStore(settings.sessions_dir / "suggestions.json")


def check_lang(lang: str) -> str:
    if lang not in LANGS:
        raise HTTPException(status_code=404, detail=f"Unknown language {lang!r}")
    return lang


class Suggestion(BaseModel):
    label: str = Field(min_length=1, max_length=MAX_LABEL)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class SuggestionList(BaseModel):
    items: list[Suggestion] = Field(max_length=MAX_ITEMS)


async def suggestions_changed(custom: dict[str, Any]) -> dict[str, Any]:
    await broadcast_all({"type": "suggestions", "custom": custom})
    return {"custom": custom}


@app.get("/api/suggestions", dependencies=api)
def get_suggestions():
    return {"custom": suggestion_store().load()}


@app.put("/api/suggestions/{lang}", dependencies=api)
async def put_suggestions(lang: str, req: SuggestionList):
    items = [{"label": i.label.strip(), "text": i.text.strip()} for i in req.items]
    if any(not i["label"] or not i["text"] for i in items):
        raise HTTPException(status_code=422, detail="Every prompt needs a label and a text.")
    return await suggestions_changed(suggestion_store().set(check_lang(lang), items))


@app.delete("/api/suggestions/{lang}", dependencies=api)
async def reset_suggestions(lang: str):
    return await suggestions_changed(suggestion_store().reset(check_lang(lang)))


# ----- skills -----

class SkillContent(BaseModel):
    content: str


class NewSkill(SkillContent):
    name: str


class SkillState(BaseModel):
    enabled: bool


def skill_call(func, *args):
    try:
        return func(settings.project_dir, *args)
    except skill_files.SkillError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def log_skill_change(action: str, name: str) -> None:
    # Takes effect in each chat from its next message (the agent restarts with the new skills).
    logger.warning("skill %s %s from the web UI", name, action)


@app.get("/api/skills", dependencies=api)
def get_skills():
    return skill_call(skill_files.list_skills)


@app.post("/api/skills", status_code=201, dependencies=api)
def post_skill(req: NewSkill):
    skill = skill_call(skill_files.create_skill, req.name, req.content)
    log_skill_change("created", req.name)
    return skill


@app.get("/api/skills/{name}", dependencies=api)
def get_skill(name: str):
    return skill_call(skill_files.read_skill, name)


@app.put("/api/skills/{name}", dependencies=api)
def put_skill(name: str, req: SkillContent):
    skill = skill_call(skill_files.update_skill, name, req.content)
    log_skill_change("updated", name)
    return skill


@app.patch("/api/skills/{name}", dependencies=api)
def patch_skill(name: str, req: SkillState):
    skill = skill_call(skill_files.set_enabled, name, req.enabled)
    log_skill_change("enabled" if req.enabled else "disabled", name)
    return skill


@app.delete("/api/skills/{name}", dependencies=api)
def delete_skill(name: str):
    skill_call(skill_files.delete_skill, name)
    log_skill_change("deleted", name)
    return {"ok": True}


# ----- WebSocket -----

@app.websocket("/ws")
async def websocket(ws: WebSocket):
    if not token_ok(ws.query_params.get("token")):
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = Connection(ws)
    connections.add(conn)
    await conn.send({"type": "chats", "chats": chat_list()})
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await conn.send({"type": "notice", "level": "error", "text": "Invalid JSON"})
                continue
            await handle_ws(conn, msg)
    except WebSocketDisconnect:
        pass
    finally:
        connections.discard(conn)


async def handle_ws(conn: Connection, msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    if kind == "estop":
        await emergency_stop("websocket")
        return
    session = sessions.get(str(msg.get("chatId", "")))
    if session is None:
        await conn.send({"type": "notice", "level": "error", "text": "Chat not found"})
        return
    if kind == "subscribe":
        conn.chat_id = session.id
        await conn.send({"type": "history", "chatId": session.id, "events": session.events,
                         "busy": session.busy})
    elif kind == "chat":
        content = str(msg.get("content", "")).strip()
        if not content:
            return
        conn.chat_id = session.id
        try:
            await session.send(content)
        except RuntimeError as exc:
            await conn.send({"type": "notice", "level": "error", "text": str(exc)})
    elif kind == "approval":
        if not session.resolve_approval(str(msg.get("id")), bool(msg.get("approve")),
                                        str(msg.get("note", ""))[:500]):
            await conn.send({"type": "notice", "level": "warning",
                             "text": "That approval request is no longer pending."})
    elif kind == "interrupt":
        await session.interrupt()
    else:
        await conn.send({"type": "notice", "level": "error", "text": f"Unknown message {kind!r}"})
