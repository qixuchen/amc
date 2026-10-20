"""AIMessage / ToolMessage pairing."""

from __future__ import annotations

from typing import Any

import pytest

from src.trajectory_store.commit.pairing import pair_ai_tool_steps

from helpers import sql_retry_steps

pytestmark = pytest.mark.unit


def test_alternating_pairs() -> None:
    pairs = pair_ai_tool_steps(sql_retry_steps())
    assert [(p.ai_step, p.tool_step) for p in pairs] == [(1, 2), (3, 4), (5, 6), (7, 8)]
    assert not any(p.pending_output for p in pairs)


def test_pending_when_fewer_tools_than_ai_messages() -> None:
    """More AIMessage rows than ToolMessage rows -> last pairs are pending."""
    steps: list[dict[str, Any]] = [
        {"Step": 1, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 1")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 2, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 2")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 3, "Thinking": "", "Action": "", "Action_result": "{'status': 'success'}", "meta": {"role": "ToolMessage"}},
    ]
    pairs = pair_ai_tool_steps(steps)
    assert len(pairs) == 2
    assert pairs[0].pending_output is False
    assert pairs[1].pending_output is True
    assert "pending_output" in pairs[1].quality_flags


def test_compatible_tool_output_goes_to_matching_action() -> None:
    """An unanswered SQL call followed by write_report: the report output pairs with write_report."""
    steps: list[dict[str, Any]] = [
        {"Step": 1, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 1")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 2, "Thinking": "", "Action": 'write_report(content="# R")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 3, "Thinking": "", "Action": "", "Action_result": "{'status': 'success', 'path': '/tmp/r.md'}", "meta": {"role": "ToolMessage"}},
    ]
    pairs = pair_ai_tool_steps(steps)
    sql, report = pairs
    assert sql.pending_output is True
    assert sql.tool_step is None
    assert report.pending_output is False
    assert report.tool_step == 3


def test_batched_ai_then_tools_keeps_fifo_when_compatibility_ties() -> None:
    steps: list[dict[str, Any]] = [
        {"Step": 1, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 1")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 2, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 2")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 3, "Thinking": "", "Action": 'local_db_sql(file_path="a.db", command="SELECT 3")', "Action_result": "", "meta": {"role": "AIMessage"}},
        {"Step": 4, "Thinking": "", "Action": "", "Action_result": "{'status': 'success', 'rows': 1}", "meta": {"role": "ToolMessage"}},
        {"Step": 5, "Thinking": "", "Action": "", "Action_result": "{'status': 'success', 'rows': 2}", "meta": {"role": "ToolMessage"}},
        {"Step": 6, "Thinking": "", "Action": "", "Action_result": "{'status': 'success', 'rows': 3}", "meta": {"role": "ToolMessage"}},
    ]
    pairs = pair_ai_tool_steps(steps)
    assert [p.ai_step for p in pairs] == [1, 2, 3]
    assert [p.tool_step for p in pairs] == [4, 5, 6]
