"""Action parsing and tool-output truncation."""

from __future__ import annotations

import pytest

from src.trajectory_store.commit.normalizer import (
    parse_local_db_sql_action,
    parse_tool_output_to_dict,
    truncate_tool_output,
)

from helpers import sql_retry_steps

pytestmark = pytest.mark.unit


def test_parse_local_db_sql_action() -> None:
    ai_with_action = next(s for s in sql_retry_steps() if s["meta"]["role"] == "AIMessage")
    parsed = parse_local_db_sql_action(str(ai_with_action["Action"]))
    assert parsed is not None
    assert parsed["tool_name"] == "local_db_sql"
    assert "file_path" in parsed
    assert "command" in parsed
    assert parsed["file_path"].endswith(".sqlite")


def test_truncate_long_action_result() -> None:
    long_text = str({"status": "success", "rows": [[i, f"province_{i}"] for i in range(200)]})
    assert len(long_text) > 200
    max_chars = 400
    out, truncated = truncate_tool_output(long_text, max_chars=max_chars)
    assert truncated is True
    assert len(out) <= max_chars
    assert "truncated" in out


def test_parse_generic_function_name_and_kwargs() -> None:
    parsed = parse_local_db_sql_action("execute_sql(query='select 1', timeout=10)")
    assert parsed is not None
    assert parsed["tool_name"] == "execute_sql"
    assert parsed["query"] == "select 1"
    assert parsed["timeout"] == 10


def test_parse_tool_output_to_dict_from_python_literal_string() -> None:
    parsed = parse_tool_output_to_dict("{'status': 'success', 'rows': 3}")
    assert parsed is not None
    assert isinstance(parsed, dict)
    assert parsed["status"] == "success"
    assert parsed["rows"] == 3


def test_parse_placeholder_action_go_to() -> None:
    parsed = parse_local_db_sql_action('go to _(recep="toiletpaperhanger 1")')
    assert parsed is not None
    assert parsed["tool_name"] == "go_to"
    assert parsed["recep"] == "toiletpaperhanger 1"


def test_parse_placeholder_action_put_in_on() -> None:
    parsed = parse_local_db_sql_action('put _ in/on _(obj="toiletpaper 1", recep="toiletpaperhanger 1")')
    assert parsed is not None
    assert parsed["tool_name"] == "put_in_on"
    assert parsed["obj"] == "toiletpaper 1"
    assert parsed["recep"] == "toiletpaperhanger 1"
