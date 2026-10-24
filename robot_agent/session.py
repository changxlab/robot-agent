"""Robot agent chat sessions built on ClaudeSDKClient.

One long-lived SDK client per chat (the pattern from Anthropic's simple-chatapp demo).
Every Bash call is classified by a PreToolUse hook (robot_agent.safety); calls that need a
human decision are sent to the browser through ``can_use_tool`` and wait for the operator
(the pattern from the ask-user-question-previews demo).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import safety
from .config import Settings
from .media import media_in_output
from .store import ChatStore

logger = logging.getLogger("robot_agent")

MAX_TOOL_OUTPUT = 12_000

SYSTEM_PROMPT = """\
You are the operator assistant for a Unitree B2 quadruped robot with one AgileX Piper arm and
five cameras (B2 front/rear, RealSense D455, Orbbec Gemini, iCamera multispectral), with Nav2
navigation on the same computer (ROS 2 Humble). Follow the operating rules in CLAUDE.md, use the
robot skills and the ./robot tool, and never invent sensor readings.
"""

ROBOT_SKILLS_DIR = ".claude/skills"


def robot_skills(project_dir) -> list[str]:
    """Names of the project's robot skills (the agent sees only these)."""
    root = project_dir / ROBOT_SKILLS_DIR
    return sorted(p.parent.name for p in root.glob("*/SKILL.md"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, dict) and item.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


class ChatSession:
    def __init__(self, settings: Settings,
                 broadcast: Callable[[str, dict[str, Any]], Awaitable[None]],
                 store: ChatStore | None = None):
        self.id = str(uuid.uuid4())
        self.settings = settings
        self.title = "New chat"
        self.created_at = now()
        self.updated_at = self.created_at
        self.events: list[dict[str, Any]] = []
        self.busy = False
        # Claude Code session id; used to resume the agent's context after a restart.
        self.claude_session_id: str | None = None
        self._store = store
        self._resuming = False
        self._broadcast = broadcast
        self._client: ClaudeSDKClient | None = None
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        # Robot skills the running agent process was started with.
        self._agent_skills: list[str] | None = None
        self._ready = asyncio.Event()
        self._approvals: dict[str, asyncio.Future] = {}
        self._decisions: dict[str, safety.Decision] = {}
        # Tool-call ids already shown; some model gateways repeat a call with an empty input.
        self._tool_ids: set[str] = set()
        self._result_ids: set[str] = set()
        # Context for the agent prepended to the next request (e.g. a robot mode switch).
        self._notes: list[str] = []
        if store is not None:
            self._save_meta()

    @classmethod
    def restore(cls, settings: Settings,
                broadcast: Callable[[str, dict[str, Any]], Awaitable[None]],
                store: ChatStore, meta: dict[str, Any],
                events: list[dict[str, Any]]) -> "ChatSession":
        """Rebuild a chat saved by a previous server process."""
        session = cls(settings, broadcast)
        session._store = store
        session.id = meta["id"]
        session.title = meta.get("title") or "New chat"
        session.created_at = meta.get("createdAt") or now()
        session.claude_session_id = meta.get("claudeSessionId")
        session.events = events
        session.updated_at = events[-1].get("ts", session.created_at) if events else (
            meta.get("updatedAt") or session.created_at)
        turn_events = [e for e in events if e.get("type") != "mode"]
        if turn_events and turn_events[-1].get("type") != "done":
            # The server stopped in the middle of a turn.
            for event in ({"type": "error", "text": "The server restarted before this request "
                                                    "finished."},
                          {"type": "done", "ok": False}):
                session._record({**event, "chatId": session.id, "ts": now()})
        return session

    # ----- public API -----

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "createdAt": self.created_at,
                "updatedAt": self.updated_at, "busy": self.busy}

    async def send(self, text: str) -> None:
        if self.busy:
            raise RuntimeError("The agent is still working on the previous request.")
        self.busy = True
        if self.title == "New chat":
            self.title = text[:48] + ("…" if len(text) > 48 else "")
        await self._emit({"type": "user", "text": text})
        self._save_meta()
        prompt = "\n\n".join([*self._notes, text])
        self._notes.clear()
        if self._worker is not None and \
                self._agent_skills != robot_skills(self.settings.project_dir):
            # Skills were changed in the UI: restart the agent; it resumes this chat's context.
            await self._stop_worker()
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name=f"chat-{self.id}")
        await self._queue.put(prompt)

    async def mode_changed(self, mode: str) -> None:
        """Tell the operator now and the agent with the next request that the mode changed."""
        label = "SIMULATION" if mode == "sim" else "REAL hardware"
        self._notes = [n for n in self._notes if not n.startswith("[Operator note: robot mode")]
        self._notes.append(f"[Operator note: robot mode switched to {label} ({mode}). Earlier "
                           "readings in this chat may come from the other mode; re-check status "
                           "before acting.]")
        await self._emit({"type": "mode", "mode": mode})

    def resolve_approval(self, approval_id: str, approve: bool, note: str = "") -> bool:
        future = self._approvals.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result((approve, note))
        return True

    async def interrupt(self, reason: str = "Interrupted by operator") -> None:
        self._deny_pending(reason)
        if self.busy and self._client is not None:
            try:
                await self._client.interrupt()
            except Exception:  # the turn may already be finishing
                logger.exception("interrupt failed for chat %s", self.id)

    async def close(self) -> None:
        self._deny_pending("Chat closed")
        await self._stop_worker()

    async def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        await self._queue.put(None)
        try:
            await asyncio.wait_for(worker, timeout=10)
        except (asyncio.TimeoutError, Exception):
            worker.cancel()
        self._detach(worker)

    # ----- worker: owns the SDK client for its whole lifetime -----

    async def _run(self) -> None:
        worker = asyncio.current_task()
        resume = self.claude_session_id
        self._resuming = resume is not None
        try:
            async with ClaudeSDKClient(options=self._options(resume)) as client:
                self._client = client
                while (prompt := await self._queue.get()) is not None:
                    if not await self._turn(client, prompt):
                        break  # the agent process failed; the next message starts a new one
        except Exception as exc:
            logger.exception("agent session %s failed", self.id)
            if self._worker is worker:
                self._detach(worker)
                while not self._queue.empty():
                    self._queue.get_nowait()
                await self._emit({"type": "error", "text": f"Agent session failed: {exc}"})
                await self._forget_failed_resume()
                await self._finish(ok=False)
        finally:
            self._detach(worker)

    async def _turn(self, client: ClaudeSDKClient, prompt: str) -> bool:
        """Run one request; returns False when the agent process can no longer be used."""
        ok = False
        alive = True
        try:
            await client.query(prompt)
            async for message in client.receive_response():
                await self._handle(message)
                if isinstance(message, ResultMessage):
                    ok = not message.is_error
        except Exception as exc:
            logger.exception("turn failed in chat %s", self.id)
            alive = False
            # Let the next message start a new worker before this one finishes closing.
            self._detach(asyncio.current_task())
            await self._emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            await self._forget_failed_resume()
        finally:
            await self._finish(ok)
        return alive

    def _detach(self, worker: asyncio.Task | None) -> None:
        if self._worker is worker:
            self._worker = None
            self._client = None

    async def _forget_failed_resume(self) -> None:
        if not self._resuming:
            return
        logger.warning("could not resume Claude session %s for chat %s",
                       self.claude_session_id, self.id)
        self._resuming = False
        self.claude_session_id = None
        self._save_meta()
        await self._emit({"type": "error", "text": "Could not restore the agent's previous "
                          "context. The chat history is kept; your next message starts a "
                          "fresh agent context."})

    async def _finish(self, ok: bool) -> None:
        self._deny_pending("Turn ended")
        self.busy = False
        await self._emit({"type": "done", "ok": ok})

    # ----- SDK configuration -----

    def _options(self, resume: str | None = None) -> ClaudeAgentOptions:
        s = self.settings
        self._agent_skills = robot_skills(s.project_dir)
        return ClaudeAgentOptions(
            model=s.model,
            system_prompt=SYSTEM_PROMPT,
            cwd=str(s.project_dir),
            tools=["Bash", "Read", "Glob", "Grep", "Skill"],
            allowed_tools=["Read", "Glob", "Grep"],
            skills=self._agent_skills,
            setting_sources=["project"],
            permission_mode="default",
            hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[self._pre_tool_use])]},
            can_use_tool=self._can_use_tool,
            max_turns=s.max_turns,
            env=s.agent_env(),
            resume=resume,
            session_store=self._store.transcripts if self._store else None,
            stderr=lambda line: logger.debug("claude: %s", line),
        )

    async def _pre_tool_use(self, input_data: dict[str, Any], tool_use_id: str | None,
                            context: Any) -> dict[str, Any]:
        command = str((input_data.get("tool_input") or {}).get("command", ""))
        decision = safety.classify(command)
        if tool_use_id:
            self._decisions[tool_use_id] = decision
        logger.info("bash %s [%s]: %s", decision.action, decision.category, command)
        await self._emit({"type": "safety", "toolUseId": tool_use_id, "action": decision.action,
                          "category": decision.category, "reason": decision.reason})
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision.action,
            "permissionDecisionReason": decision.reason,
        }}

    async def _can_use_tool(self, tool_name: str, tool_input: dict[str, Any],
                            context: ToolPermissionContext):
        decision = self._decisions.get(context.tool_use_id or "")
        approval_id = str(uuid.uuid4())
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._approvals[approval_id] = future
        await self._emit({
            "type": "approval_request",
            "id": approval_id,
            "toolUseId": context.tool_use_id,
            "tool": tool_name,
            "command": tool_input.get("command") if tool_name == "Bash" else None,
            "input": tool_input,
            "description": tool_input.get("description", ""),
            "reason": (decision.reason if decision else None) or context.decision_reason or "",
            "category": decision.category if decision else "unknown",
            "timeout": self.settings.approval_timeout,
        })
        try:
            approve, note = await asyncio.wait_for(future, self.settings.approval_timeout)
        except asyncio.TimeoutError:
            approve, note = False, f"no operator response within {self.settings.approval_timeout}s"
        finally:
            self._approvals.pop(approval_id, None)
        await self._emit({"type": "approval_result", "id": approval_id, "approved": approve,
                          "note": note})
        if approve:
            return PermissionResultAllow(updated_input=tool_input)
        message = "The operator declined this command"
        message += f": {note}" if note else "."
        message += " Do not retry it; ask the operator how to proceed."
        return PermissionResultDeny(message=message)

    def _deny_pending(self, reason: str) -> None:
        for future in list(self._approvals.values()):
            if not future.done():
                future.set_result((False, reason))

    # ----- message → UI events -----

    async def _handle(self, message: Any) -> None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    # Claude Code reports API/stream failures as synthetic assistant text.
                    kind = "error" if message.model == "<synthetic>" else "assistant"
                    await self._emit({"type": kind, "text": block.text})
                elif isinstance(block, ToolUseBlock):
                    if block.id in self._tool_ids:
                        logger.warning("ignoring repeated tool call %s (%s) input=%s",
                                       block.id, block.name, block.input)
                        continue
                    self._tool_ids.add(block.id)
                    await self._emit({"type": "tool_use", "id": block.id, "name": block.name,
                                      "input": block.input})
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    if block.tool_use_id in self._result_ids:
                        continue
                    self._result_ids.add(block.tool_use_id)
                    text = _tool_result_text(block.content)
                    found = media_in_output(text, self.settings.project_dir)
                    if len(text) > MAX_TOOL_OUTPUT:
                        text = text[:MAX_TOOL_OUTPUT] + "\n… (truncated)"
                    await self._emit({"type": "tool_result", "toolUseId": block.tool_use_id,
                                      "output": text, "isError": bool(block.is_error),
                                      "images": [m["url"] for m in found if m["kind"] == "image"],
                                      "media": found})
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            self._resuming = False
            self._set_claude_session(message.data.get("session_id"))
            skills = message.data.get("skills") or []
            await self._emit({"type": "init", "model": message.data.get("model"),
                              "skills": [s if isinstance(s, str) else s.get("name") for s in skills]})
        elif isinstance(message, ResultMessage):
            self._set_claude_session(message.session_id)
            if message.is_error:
                await self._emit({"type": "error",
                                  "text": message.result or f"Agent stopped: {message.subtype}"})
            await self._emit({"type": "result", "ok": not message.is_error,
                              "durationMs": message.duration_ms, "turns": message.num_turns,
                              "costUsd": message.total_cost_usd})

    def _set_claude_session(self, session_id: str | None) -> None:
        if session_id and session_id != self.claude_session_id:
            self.claude_session_id = session_id
            self._save_meta()

    # ----- persistence -----

    def _save_meta(self) -> None:
        if self._store is not None:
            self._store.save_meta(self.id, {
                "id": self.id, "title": self.title, "createdAt": self.created_at,
                "updatedAt": self.updated_at, "claudeSessionId": self.claude_session_id})

    def _record(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.updated_at = event["ts"]
        if self._store is not None:
            self._store.append_event(self.id, event)
            if event["type"] == "done":
                self._save_meta()

    async def _emit(self, event: dict[str, Any]) -> None:
        event = {**event, "chatId": self.id, "ts": now()}
        self._record(event)
        await self._broadcast(self.id, event)
