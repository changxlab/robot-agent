import asyncio
import json

import pytest

pytest.importorskip("litellm")

from copilot_stream_fix import proxy_handler_instance  # noqa: E402


def sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


def tool_start(index, tool_id):
    return {"type": "content_block_start", "index": index,
            "content_block": {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {}}}


def delta(index, text):
    return {"type": "content_block_delta", "index": index,
            "delta": {"type": "input_json_delta", "partial_json": text}}


def repair(events):
    async def source():
        for e in events:
            yield sse(e)

    async def run():
        out = []
        async for chunk in proxy_handler_instance.async_post_call_streaming_iterator_hook(
                None, source(), {}):
            for raw in chunk.decode().split("\n\n"):
                if raw.strip():
                    out.append(json.loads(raw.split("data: ", 1)[1]))
        return out

    return asyncio.run(run())


def test_parallel_calls_drop_duplicates_and_orphan_deltas():
    out = repair([
        {"type": "message_start", "message": {}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_stop", "index": 0},
        tool_start(1, "a"), delta(1, '{"command":"date"}'), {"type": "content_block_stop", "index": 1},
        tool_start(2, "a"), delta(2, ""), {"type": "content_block_stop", "index": 2},
        tool_start(3, "b"), delta(3, '{"command":"uptime"}'), {"type": "content_block_stop", "index": 3},
        delta(4, ""),
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ])
    starts = [(e["index"], e["content_block"].get("id")) for e in out
              if e["type"] == "content_block_start"]
    assert starts == [(0, None), (1, "a"), (2, "b")]
    deltas = [(e["index"], e["delta"]["partial_json"]) for e in out
              if e["type"] == "content_block_delta"]
    assert deltas == [(1, '{"command":"date"}'), (2, '{"command":"uptime"}')]
    assert [e["index"] for e in out if e["type"] == "content_block_stop"] == [0, 1, 2]


def test_single_call_stop_reason_becomes_tool_use():
    out = repair([
        {"type": "message_start", "message": {}},
        tool_start(0, "a"), delta(0, '{"command":"ls"}'), {"type": "content_block_stop", "index": 0},
        tool_start(1, "a"), delta(1, ""), {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ])
    assert sum(e["type"] == "content_block_start" for e in out) == 1
    assert next(e for e in out if e["type"] == "message_delta")["delta"]["stop_reason"] == "tool_use"


def test_text_only_stream_is_unchanged():
    events = [
        {"type": "message_start", "message": {}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]
    assert repair(events) == events


def test_duplicate_stop_dropped_and_open_block_closed_before_message_delta():
    out = repair([
        {"type": "message_start", "message": {}},
        tool_start(0, "a"), delta(0, '{"command":"date"}'), {"type": "content_block_stop", "index": 0},
        {"type": "content_block_stop", "index": 0},
        tool_start(1, "b"), delta(1, '{"command":"ls"}'),
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ])
    kinds = [(e["type"], e.get("index")) for e in out]
    assert kinds == [("message_start", None), ("content_block_start", 0),
                     ("content_block_delta", 0), ("content_block_stop", 0),
                     ("content_block_start", 1), ("content_block_delta", 1),
                     ("content_block_stop", 1), ("message_delta", None), ("message_stop", None)]


def test_copilot_parallel_calls_with_early_finish_reason_end_to_end():
    """The Copilot chunk sequence seen for three parallel calls, through LiteLLM's real
    AnthropicStreamWrapper plus the hook: every call must arrive complete."""
    from litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator import (
        AnthropicStreamWrapper,
    )
    from litellm.types.utils import (ChatCompletionDeltaToolCall, Delta, Function,
                                     ModelResponseStream, StreamingChoices)

    def chunk(tool_id=None, name=None, args="", finish=None):
        calls = None if finish else [ChatCompletionDeltaToolCall(
            id=tool_id, index=0, type="function", function=Function(name=name, arguments=args))]
        return ModelResponseStream(choices=[StreamingChoices(
            index=0, finish_reason=finish, delta=Delta(role="assistant", tool_calls=calls))])

    upstream = [
        chunk("call_a", "Skill"), chunk(args='{"skill":"piper-arm"}'), chunk("call_a", "Skill"),
        chunk("call_b", "Skill"), chunk(args='{"skill":"robot-camera"}'),
        chunk(finish="tool_calls"),
        chunk("call_b", "Skill"), chunk("call_c", "Bash"),
        chunk(args='{"command":"./robot arm status"}'),
    ]

    async def completion_stream():
        for c in upstream:
            yield c

    async def run():
        wrapper = AnthropicStreamWrapper(completion_stream(), model="gpt-6-luna")
        out = []
        async for event in proxy_handler_instance.async_post_call_streaming_iterator_hook(
                None, wrapper, {}):
            out.append(event)
        return out

    out = asyncio.run(run())
    started, calls = set(), {}
    for e in out:
        if e["type"] == "content_block_start":
            started.add(e["index"])
            if e["content_block"]["type"] == "tool_use":
                calls[e["index"]] = [e["content_block"]["id"], e["content_block"]["name"], ""]
        elif e["type"] in ("content_block_delta", "content_block_stop"):
            assert e["index"] in started, f"orphan {e}"
            if e["type"] == "content_block_delta" and e["index"] in calls:
                calls[e["index"]][2] += e["delta"].get("partial_json", "")
    assert sorted(calls.values()) == [
        ["call_a", "Skill", '{"skill":"piper-arm"}'],
        ["call_b", "Skill", '{"skill":"robot-camera"}'],
        ["call_c", "Bash", '{"command":"./robot arm status"}'],
    ]
    stops = [e["index"] for e in out if e["type"] == "content_block_stop"]
    assert sorted(stops) == sorted(started) and len(stops) == len(set(stops))
    assert next(e for e in out if e["type"] == "message_delta")["delta"]["stop_reason"] == "tool_use"
    assert out[-1]["type"] == "message_stop"
