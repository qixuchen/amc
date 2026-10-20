"""L0/L1 summaries: injected LLM summarizer and rule-based fallback."""

from __future__ import annotations

from src.trajectory_store.commit.summarizer import summarize_trajectory


def test_llm_summarizer_result_is_preferred() -> None:
    steps = [
        {"Step": 1, "meta": {"role": "AIMessage"}, "Action": "local_db_sql(command='select 1')"},
        {"Step": 2, "meta": {"role": "ToolMessage"}, "Action_result": "{'status': 'success'}"},
    ]

    def _fake_llm(_steps):
        return ("L0 from llm", "L1 from llm")

    l0, l1 = summarize_trajectory(steps, llm_summarizer=_fake_llm)
    assert l0 == "L0 from llm"
    assert l1 == "L1 from llm"


def test_llm_failure_falls_back_to_rule_based() -> None:
    steps = [
        {"Step": 1, "meta": {"role": "AIMessage"}, "Action": "local_db_sql(command='select 1')"},
        {"Step": 2, "meta": {"role": "ToolMessage"}, "Action_result": "{'status': 'success'}"},
    ]

    def _bad_llm(_steps):
        raise RuntimeError("boom")

    l0, l1 = summarize_trajectory(steps, llm_summarizer=_bad_llm)
    assert "Trajectory with" in l0
    assert "Steps=" in l1
    assert "Key steps:" in l1
    assert "tool=local_db_sql" in l1


def test_l0_lists_actual_tool_names() -> None:
    steps = [
        {"Step": 1, "meta": {"role": "AIMessage"}, "Action": 'exec(command="ls")'},
        {"Step": 2, "meta": {"role": "ToolMessage"}, "Action_result": "a.csv"},
        {"Step": 3, "meta": {"role": "AIMessage"}, "Action": 'read(path="a.csv")'},
        {"Step": 4, "meta": {"role": "ToolMessage"}, "Action_result": "x,y"},
        {"Step": 5, "meta": {"role": "AIMessage"}, "Action": "local_db_sql(command='select 1')"},
        {"Step": 6, "meta": {"role": "ToolMessage"}, "Action_result": "{'status': 'success'}"},
    ]

    l0, _ = summarize_trajectory(steps)
    assert l0 == "Trajectory with 3 actions, tools=exec,local_db_sql,read."

