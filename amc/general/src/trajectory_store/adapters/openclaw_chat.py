"""Convert OpenClaw chat.jsonl transcripts (DataClaw runs) into trajectory steps.

Each toolCall becomes an AIMessage step immediately followed by the ToolMessage carrying
its result. Results are matched by toolCallId because one assistant message may issue
several calls whose results arrive later and in any order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONVERTER_ID = "openclaw_chat/1"

_QUERY_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


@dataclass
class ConvertedTrajectory:
    steps: list[dict[str, Any]]
    query: str
    final_response: str
    stats: dict[str, int] = field(default_factory=dict)


def format_tool_call_action(name: str, arguments: Any) -> str:
    """`name(k=<json>, ...)`, parseable by normalizer.parse_local_db_sql_action."""
    name = str(name or "").strip()
    if not name:
        return ""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"arguments": arguments}
    if not isinstance(arguments, dict) or not arguments:
        return f"{name}()"
    parts: list[str] = []
    for k, v in arguments.items():
        if isinstance(v, str):
            value = json.dumps(v, ensure_ascii=False)
        else:
            value = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        parts.append(f"{k}={value}")
    return f"{name}({', '.join(parts)})"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            value = block.get("text")
            if isinstance(value, str) and value:
                parts.append(value)
        elif block.get("type"):
            parts.append(f"[{block.get('type')}]")
    return "\n".join(parts)


def _step(*, role: str, meta: dict[str, Any], thinking: str = "", action: str = "",
          action_result: str = "", response: str = "") -> dict[str, Any]:
    return {
        "Step": 0,
        "Thinking": thinking,
        "Action": action,
        "Action_result": action_result,
        "Response": response,
        "meta": {"role": role, **meta},
    }


def load_chat_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    bad = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(event, dict):
            events.append(event)
    return events, bad


def convert_chat_jsonl(path: Path) -> ConvertedTrajectory:
    events, bad = load_chat_events(path)
    converted = convert_chat_events(events)
    converted.stats["bad_lines"] = bad
    return converted


def convert_chat_events(events: list[dict[str, Any]]) -> ConvertedTrajectory:
    messages = [
        e["message"]
        for e in events
        if e.get("type") == "message" and isinstance(e.get("message"), dict)
    ]
    results: dict[str, dict[str, Any]] = {}
    for m in messages:
        call_id = m.get("toolCallId")
        if m.get("role") == "toolResult" and call_id and call_id not in results:
            results[str(call_id)] = m

    stats = {"tool_calls": 0, "parallel_messages": 0, "missing_results": 0, "orphan_results": 0, "bad_lines": 0}
    steps: list[dict[str, Any]] = []
    used: set[str] = set()
    query = ""
    final_response = ""
    group = 0

    for m in messages:
        role = m.get("role")
        if role == "user":
            if not query:
                query = _QUERY_PREFIX_RE.sub("", _content_text(m.get("content")).strip(), count=1).strip()
            continue
        if role != "assistant":
            continue

        content = m.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": _content_text(content)}]
        blocks = [b for b in blocks if isinstance(b, dict)]
        thinking = "\n".join(
            str(b.get("thinking")) for b in blocks if b.get("type") == "thinking" and b.get("thinking")
        )
        texts = "\n".join(str(b.get("text")) for b in blocks if b.get("type") == "text" and b.get("text"))
        calls = [b for b in blocks if b.get("type") == "toolCall"]
        if not calls:
            if texts:
                final_response = texts
            continue

        parallel = len(calls) > 1
        if parallel:
            group += 1
            stats["parallel_messages"] += 1
        for i, call in enumerate(calls):
            call_id = str(call.get("id") or "")
            name = str(call.get("name") or "")
            ai_meta: dict[str, Any] = {"toolCallId": call_id, "toolName": name}
            if parallel:
                ai_meta["parallel_group"] = group
            steps.append(
                _step(
                    role="AIMessage",
                    meta=ai_meta,
                    thinking=thinking if i == 0 else "",
                    action=format_tool_call_action(name, call.get("arguments")),
                    response=texts if i == 0 else "",
                )
            )
            stats["tool_calls"] += 1

            res = results.get(call_id) if call_id else None
            if res is None:
                stats["missing_results"] += 1
                continue
            used.add(call_id)
            tool_meta: dict[str, Any] = {
                "toolCallId": call_id,
                "toolName": str(res.get("toolName") or name),
                "isError": bool(res.get("isError")),
            }
            details = res.get("details")
            if isinstance(details, dict) and details.get("exitCode") is not None:
                tool_meta["exitCode"] = details["exitCode"]
            steps.append(_step(role="ToolMessage", meta=tool_meta, action_result=_content_text(res.get("content"))))

    stats["orphan_results"] = sum(
        1 for m in messages if m.get("role") == "toolResult" and str(m.get("toolCallId") or "") not in used
    )
    for n, step in enumerate(steps, start=1):
        step["Step"] = n
    return ConvertedTrajectory(steps=steps, query=query, final_response=final_response, stats=stats)
