from __future__ import annotations

from typing import Any


def _ai(step: int, action: str, thinking: str = "") -> dict[str, Any]:
    return {"Step": step, "Thinking": thinking, "Action": action, "Action_result": "", "Response": "", "meta": {"role": "AIMessage"}}


def _tool(step: int, result: str) -> dict[str, Any]:
    return {"Step": step, "Thinking": "", "Action": "", "Action_result": result, "Response": "", "meta": {"role": "ToolMessage"}}


def tiny_steps(*, result: str = "{'status': 'success', 'rows': 3}") -> list[dict[str, Any]]:
    return [
        _ai(1, "exec(command='ls ./database')", "list files first"),
        _tool(2, result),
        _ai(3, "read(path='./database/a.csv')", "read the csv"),
        _tool(4, "{'status': 'success'}"),
    ]


DB = "/tmp/demo.sqlite"


def sql_retry_steps() -> list[dict[str, Any]]:
    """List tables, fail a query, retry it on the same db, then write a report."""
    return [
        _ai(1, f'local_db_sql(file_path="{DB}", command="SELECT name FROM sqlite_master")', "find tables"),
        _tool(2, "{'status': 'success', 'data': ['company_profile_core']}"),
        _ai(3, f'local_db_sql(file_path="{DB}", command="SELECT revnue FROM company_profile_core")', "query revenue"),
        _tool(4, "{'status': 'failed', 'error': 'no such column: revnue'}"),
        _ai(5, f'local_db_sql(file_path="{DB}", command="SELECT revenue FROM company_profile_core")', "fix the typo"),
        _tool(6, "{'status': 'success', 'rows': 15}"),
        _ai(7, 'write_report(content="# Report")', "summarize"),
        _tool(8, "{'status': 'success', 'path': '/tmp/report.md'}"),
    ]
