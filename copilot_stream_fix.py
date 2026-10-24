"""LiteLLM proxy callback that repairs Anthropic /v1/messages streams built from GitHub Copilot.

Copilot's OpenAI-style stream repeats each tool call's header (same id and name, empty
arguments) after the arguments - sometimes after finish_reason - and reports
finish_reason "stop" for single tool calls. LiteLLM's OpenAI->Anthropic stream adapter turns
that into:

* a second, empty ``tool_use`` block with the same id, which Claude Code executes and rejects
  ("InputValidationError: The required parameter `command` is missing") and which the robot UI
  shows as "Using skill: skill";
* a ``content_block_delta`` for a block that was never started, which Claude Code reports as
  "API Error: Part of the response never arrived";
* ``stop_reason: end_turn`` although the message contains a tool call.

Copilot can also send ``finish_reason`` in the middle of parallel tool calls, before the last
call. LiteLLM's AnthropicStreamWrapper (1.80.x) then emits no ``content_block_start`` for the
blocks that follow - the call's id and name are lost and only its argument deltas go out, so
Claude Code reports "Part of the response never arrived" and the call is never run. The patch
below lets the wrapper start those blocks; the hook then drops the repeated stop events this
causes and closes any block left open before the end of the message.

This hook drops the duplicate and orphan block events and corrects the stop reason.
Enable it in config.yaml:

    litellm_settings:
      callbacks: copilot_stream_fix.proxy_handler_instance
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from litellm.integrations.custom_logger import CustomLogger


class AnthropicStreamRepair:
    """Filters one Anthropic SSE stream, event by event."""

    def __init__(self) -> None:
        self.seen_tool_ids: set[str] = set()
        self.remap: dict[int, int] = {}  # upstream block index -> contiguous output index
        self.open: set[int] = set()  # output blocks started and not stopped yet
        self.has_tool_use = False

    def _close_open(self) -> list[dict[str, Any]]:
        closing = [{"type": "content_block_stop", "index": i} for i in sorted(self.open)]
        self.open.clear()
        return closing

    def process(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """The events to send in place of ``event`` (none, the event, or extra stops first)."""
        etype = event.get("type")
        index = event.get("index")
        if etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                tool_id = block.get("id")
                if tool_id and tool_id in self.seen_tool_ids:
                    return []
                if tool_id:
                    self.seen_tool_ids.add(tool_id)
                self.has_tool_use = True
            self.remap[index] = len(self.remap)
            event["index"] = self.remap[index]
            self.open.add(event["index"])
            return [event]
        if etype in ("content_block_delta", "content_block_stop"):
            if index not in self.remap or self.remap[index] not in self.open:
                return []
            event["index"] = self.remap[index]
            if etype == "content_block_stop":
                self.open.discard(event["index"])
            return [event]
        if etype == "message_delta":
            delta = event.get("delta") or {}
            if self.has_tool_use and delta.get("stop_reason") == "end_turn":
                delta["stop_reason"] = "tool_use"
            return self._close_open() + [event]
        if etype == "message_stop":
            return self._close_open() + [event]
        return [event]


def patch_litellm_stream_wrapper() -> bool:
    """Make LiteLLM start content blocks that arrive after the upstream finish_reason."""
    try:
        from litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator import (
            AnthropicStreamWrapper,
        )
    except ImportError:
        return False
    original = AnthropicStreamWrapper._should_start_new_content_block
    if getattr(original, "copilot_stream_fix", False):
        return True

    def should_start_new_content_block(self, chunk):
        start = original(self, chunk)
        if start and getattr(self, "sent_content_block_finish", False):
            # Otherwise __anext__ skips the content_block_start for this block.
            self.sent_content_block_finish = False
        return start

    should_start_new_content_block.copilot_stream_fix = True  # type: ignore[attr-defined]
    AnthropicStreamWrapper._should_start_new_content_block = should_start_new_content_block
    return True


def _parse_sse(raw: str) -> tuple[str | None, dict[str, Any] | None]:
    event_name, data = None, None
    for line in raw.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
            except ValueError:
                return event_name, None
    return event_name, data if isinstance(data, dict) else None


class CopilotStreamFix(CustomLogger):
    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict: Any, response: Any, request_data: dict,
    ) -> AsyncGenerator[Any, None]:
        repair = AnthropicStreamRepair()
        buffer, is_bytes = "", True
        async for chunk in response:
            if isinstance(chunk, dict) and "type" in chunk:
                for event in repair.process(chunk):
                    yield event
                continue
            if not isinstance(chunk, (bytes, str)):
                # /chat/completions chunks (ModelResponseStream) pass through untouched.
                yield chunk
                continue
            is_bytes = isinstance(chunk, bytes)
            buffer += chunk.decode("utf-8") if is_bytes else chunk
            out = []
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                event_name, data = _parse_sse(raw)
                if data is None or "type" not in data:
                    out.append(raw + "\n\n")
                    continue
                for event in repair.process(data):
                    name = event_name if event is data and event_name else event["type"]
                    out.append(f"event: {name}\ndata: {json.dumps(event)}\n\n")
            if out:
                text = "".join(out)
                yield text.encode("utf-8") if is_bytes else text
        if buffer:
            yield buffer.encode("utf-8") if is_bytes else buffer


patch_litellm_stream_wrapper()
proxy_handler_instance = CopilotStreamFix()
