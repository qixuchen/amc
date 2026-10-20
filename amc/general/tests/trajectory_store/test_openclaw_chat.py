from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.trajectory_store import TrajectoryRecorder
from src.trajectory_store.adapters.openclaw_chat import convert_chat_events, convert_chat_jsonl
from src.trajectory_store.commit.normalizer import parse_local_db_sql_action
from src.trajectory_store.commit.pairing import pair_ai_tool_steps
from src.trajectory_store.commit.validator import validate_raw_steps

from chat_fixtures import (
    assistant,
    call,
    result,
    simple_run_events,
    text,
    thinking,
    user,
    write_chat,
)

pytestmark = pytest.mark.unit


def _roles(steps):
    return [s["meta"]["role"] for s in steps]


def test_sequential_run_becomes_ai_tool_pairs() -> None:
    conv = convert_chat_events(simple_run_events())
    assert _roles(conv.steps) == ["AIMessage", "ToolMessage"]
    assert [s["Step"] for s in conv.steps] == [1, 2]
    ai, tool = conv.steps
    assert ai["Thinking"] == "look at files"
    assert ai["Action"] == 'exec(command="ls ./database")'
    assert ai["meta"]["toolCallId"] == "c1"
    assert tool["Action_result"] == "a.csv\nb.csv"
    assert tool["meta"]["toolCallId"] == "c1"
    assert tool["meta"]["toolName"] == "exec"
    assert tool["meta"]["isError"] is False
    assert tool["meta"]["exitCode"] == 0
    validate_raw_steps(conv.steps)


def test_query_strips_timestamp_prefix_and_final_response_is_kept() -> None:
    conv = convert_chat_events(simple_run_events("Zhejiang, 0.71"))
    assert conv.query == "Which province ranks first?"
    assert conv.final_response == "Zhejiang, 0.71"
    assert all("Zhejiang" not in s["Response"] for s in conv.steps)


def test_parallel_calls_are_paired_by_tool_call_id() -> None:
    events = [
        user("q"),
        assistant(
            thinking("read both"),
            text("Reading two files."),
            call("a", "read", path="x.csv"),
            call("b", "exec", command="wc -l y.csv"),
        ),
        result("b", "exec", "10 y.csv"),
        result("a", "read", "col1,col2"),
    ]
    conv = convert_chat_events(events)
    assert _roles(conv.steps) == ["AIMessage", "ToolMessage", "AIMessage", "ToolMessage"]
    ai_a, tool_a, ai_b, tool_b = conv.steps
    assert ai_a["meta"]["toolCallId"] == tool_a["meta"]["toolCallId"] == "a"
    assert tool_a["Action_result"] == "col1,col2"
    assert ai_b["meta"]["toolCallId"] == tool_b["meta"]["toolCallId"] == "b"
    assert tool_b["Action_result"] == "10 y.csv"
    assert ai_a["Thinking"] == "read both" and ai_b["Thinking"] == ""
    assert ai_a["Response"] == "Reading two files." and ai_b["Response"] == ""
    assert ai_a["meta"]["parallel_group"] == ai_b["meta"]["parallel_group"]
    assert conv.stats["parallel_messages"] == 1
    pairs = pair_ai_tool_steps(conv.steps)
    assert [(p.ai_step, p.tool_step) for p in pairs] == [(1, 2), (3, 4)]


def test_error_result_is_flagged() -> None:
    events = [
        user("q"),
        assistant(call("c1", "exec", command="cat missing.csv")),
        result("c1", "exec", "No such file", is_error=True, exit_code=1),
    ]
    tool = convert_chat_events(events).steps[1]
    assert tool["meta"]["isError"] is True
    assert tool["meta"]["exitCode"] == 1


def test_call_without_result_has_no_tool_step_and_is_pending() -> None:
    events = [
        user("q"),
        assistant(call("c1", "exec", command="ls")),
        result("c1", "exec", "ok"),
        assistant(call("c2", "exec", command="sleep 999")),
    ]
    conv = convert_chat_events(events)
    assert _roles(conv.steps) == ["AIMessage", "ToolMessage", "AIMessage"]
    assert conv.stats["missing_results"] == 1
    assert pair_ai_tool_steps(conv.steps)[-1].pending_output is True


def test_orphan_result_is_ignored() -> None:
    events = [
        user("q"),
        assistant(call("c1", "exec", command="ls")),
        result("c1", "exec", "ok"),
        result("zzz", "exec", "stray"),
    ]
    conv = convert_chat_events(events)
    assert len(conv.steps) == 2
    assert conv.stats["orphan_results"] == 1


def test_run_without_tool_calls_has_no_steps() -> None:
    conv = convert_chat_events([user("q"), assistant(text("I cannot do this."), stop="stop")])
    assert conv.steps == []
    assert conv.final_response == "I cannot do this."


def test_action_string_is_parseable_by_action_parser() -> None:
    events = [
        user("q"),
        assistant(call("c1", "exec", command='grep "a\\b" f.csv', workdir="/w", timeout=30, background=False)),
        result("c1", "exec", "ok"),
        assistant(call("c2", "session_status")),
        result("c2", "session_status", "ok"),
    ]
    conv = convert_chat_events(events)
    parsed = parse_local_db_sql_action(conv.steps[0]["Action"])
    assert parsed["tool_name"] == "exec"
    assert parsed["command"] == 'grep "a\\b" f.csv'
    assert parsed["timeout"] == 30
    assert conv.steps[2]["Action"] == "session_status()"


def test_non_message_and_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = write_chat(tmp_path / "chat.jsonl", simple_run_events())
    with path.open("a", encoding="utf-8") as f:
        f.write("{not json\n\n")
    conv = convert_chat_jsonl(path)
    assert len(conv.steps) == 2
    assert conv.stats["bad_lines"] == 1


def test_converted_steps_record_end_to_end(tmp_path: Path) -> None:
    conv = convert_chat_events(simple_run_events())
    res = TrajectoryRecorder(root=tmp_path, account_id="dataclaw", agent_id="glm-5.2").record(
        steps=conv.steps, session_id="s", task_id="t", labels={}
    )
    assert res.status == "accepted"
    assert res.nodes == 1


ARCHIVE_OUTPUT = Path(os.environ.get("DATACLAW_ARCHIVE_OUTPUT", Path.home() / "archive/DA_Workflow/output"))


def test_real_dataclaw_batch_converts_cleanly() -> None:
    chats = sorted(ARCHIVE_OUTPUT.glob("task_*/glm-5.2_20260810_*/chat.jsonl"))
    if not chats:
        pytest.skip(f"no DataClaw archive at {ARCHIVE_OUTPUT}")
    for chat in chats:
        conv = convert_chat_jsonl(chat)
        if not conv.steps:
            continue
        validate_raw_steps(conv.steps)
        assert conv.stats["missing_results"] == 0, chat
        assert conv.stats["orphan_results"] == 0, chat
        n_ai = sum(1 for s in conv.steps if s["meta"]["role"] == "AIMessage")
        assert n_ai == conv.stats["tool_calls"], chat
        pairs = pair_ai_tool_steps(conv.steps)
        assert not any(p.pending_output for p in pairs), chat
        for ai, tool in zip(conv.steps[::2], conv.steps[1::2]):
            assert ai["meta"]["toolCallId"] == tool["meta"]["toolCallId"], chat
