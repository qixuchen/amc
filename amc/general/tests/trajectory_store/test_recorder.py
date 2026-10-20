from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trajectory_store import RecordResult, TrajectoryRecorder
from src.trajectory_store.commit.validator import TrajectoryValidationError

from helpers import tiny_steps

pytestmark = pytest.mark.unit


def _recorder(root: Path, **kwargs) -> TrajectoryRecorder:
    return TrajectoryRecorder(root=root, account_id="dataclaw", agent_id="glm-5.2", **kwargs)


def _record(recorder: TrajectoryRecorder, **overrides) -> RecordResult:
    kwargs = dict(
        steps=tiny_steps(),
        session_id="glm-5.2_20260810_0936_c56871",
        task_id="task_008",
        labels={"score": 1.0, "success": True},
    )
    kwargs.update(overrides)
    return recorder.record(**kwargs)


def _audit_results(root: Path) -> list[str]:
    lines = (root / "_audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["result"] for line in lines]


def test_first_record_is_accepted_and_written(tmp_path: Path) -> None:
    res = _record(_recorder(tmp_path))
    assert res.status == "accepted"
    assert res.trajectory_id.startswith("traj_") and len(res.trajectory_id) == 21
    assert res.base_path == (
        tmp_path / "accounts/dataclaw/scope/agent/glm-5.2/memories/trajectories" / res.trajectory_id
    )
    assert res.nodes == 2
    assert res.edges >= 1
    meta = json.loads((res.base_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["task_id"] == "task_008"
    assert meta["labels"] == {"score": 1.0, "success": True}
    assert json.loads((tmp_path / "_index.json").read_text())[res.trajectory_id] == str(res.base_path)


def test_owner_space_controls_directory(tmp_path: Path) -> None:
    res = _record(_recorder(tmp_path), owner_space="no_skill")
    assert res.base_path.parent.parent.parent.name == "no_skill"


def test_duplicate_record_is_idempotent_and_not_rewritten(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    first = _record(recorder)
    meta_path = first.base_path / "meta.json"
    before = meta_path.read_text(encoding="utf-8")

    second = _record(recorder)
    assert second.status == "idempotent"
    assert second.trajectory_id == first.trajectory_id
    assert second.base_path == first.base_path
    assert second.nodes == first.nodes and second.edges == first.edges
    assert meta_path.read_text(encoding="utf-8") == before
    assert _audit_results(tmp_path) == ["accepted", "idempotent"]


def test_force_rewrites_duplicate(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _record(recorder)
    assert _record(recorder, force=True).status == "accepted"


def test_idempotency_can_be_disabled(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path, idempotency=False)
    assert _record(recorder).status == "accepted"
    assert _record(recorder).status == "accepted"


def test_invalid_steps_raise_and_write_nothing(tmp_path: Path) -> None:
    bad = tiny_steps()
    bad[1]["Step"] = 1
    with pytest.raises(TrajectoryValidationError):
        _record(_recorder(tmp_path), steps=bad)
    assert not (tmp_path / "accounts").exists()
    assert _audit_results(tmp_path) == ["rejected"]


def test_long_tool_output_is_truncated_with_warning(tmp_path: Path) -> None:
    res = _record(_recorder(tmp_path, max_action_result_chars=200), steps=tiny_steps(result="x" * 5000))
    assert any("truncated" in w for w in res.warnings)
    stored = json.loads((res.base_path / "trajectory.json").read_text(encoding="utf-8"))
    assert len(stored[1]["Action_result"]) <= 200


def test_injected_llm_summarizer_is_used(tmp_path: Path) -> None:
    res = _record(_recorder(tmp_path, llm_summarizer=lambda _steps: ("L0 llm", "L1 llm")))
    assert (res.base_path / ".abstract.md").read_text(encoding="utf-8") == "L0 llm"
    assert (res.base_path / ".overview.md").read_text(encoding="utf-8") == "L1 llm"
