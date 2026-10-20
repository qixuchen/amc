"""Builders for minimal OpenClaw chat.jsonl events (shape matches DataClaw runs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def user(text: str) -> dict[str, Any]:
    return {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def assistant(*blocks: dict[str, Any], stop: str = "toolUse") -> dict[str, Any]:
    return {
        "type": "message",
        "message": {"role": "assistant", "content": list(blocks), "stopReason": stop},
    }


def thinking(text: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": text, "thinkingSignature": "reasoning"}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def call(call_id: str, name: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "toolCall", "id": call_id, "name": name, "arguments": arguments}


def result(
    call_id: str,
    name: str,
    output: str,
    *,
    is_error: bool = False,
    exit_code: int | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "toolResult",
        "toolCallId": call_id,
        "toolName": name,
        "isError": is_error,
        "content": [{"type": "text", "text": output}],
        "timestamp": 1787042358689,
    }
    if exit_code is not None:
        message["details"] = {"status": "completed", "exitCode": exit_code}
    return {"type": "message", "message": message}


def session_header() -> list[dict[str, Any]]:
    return [
        {"type": "session", "id": "s1", "version": 3, "cwd": "/root/.openclaw/workspace"},
        {"type": "model_change", "id": "m1", "provider": "openrouter", "modelId": "z-ai/glm-5.2"},
    ]


def write_chat(path: Path, events: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    return path


def simple_run_events(final_answer: str = "The answer is 42.", call_id: str = "c1") -> list[dict[str, Any]]:
    return [
        *session_header(),
        user("[Mon 2026-08-10 01:38 UTC] Which province ranks first?"),
        assistant(thinking("look at files"), call(call_id, "exec", command="ls ./database")),
        result(call_id, "exec", "a.csv\nb.csv", exit_code=0),
        assistant(thinking("done"), text(final_answer), stop="stop"),
    ]
