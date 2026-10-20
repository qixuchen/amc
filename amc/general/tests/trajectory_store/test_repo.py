from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trajectory_store.repo import LocalFSTrajectoryRepository

pytestmark = pytest.mark.unit

BUNDLE_FILES = {
    "trajectory.json",
    "raw_graph.json",
    "clean_graph.json",
    "graph_pointer.json",
    ".abstract.md",
    ".overview.md",
    "meta.json",
}


def _payload() -> dict:
    return {
        "trajectory": [{"Step": 1, "meta": {"role": "AIMessage"}, "Action": "x()"}],
        "raw_graph": {"nodes": [], "edges": []},
        "clean_graph": {"nodes": [], "edges": []},
        "abstract": "L0 text",
        "overview": "L1 text",
        "task_id": "task-a",
        "labels": {"score": 1.0},
        "nodes": 0,
        "edges": 0,
    }


def _save(repo: LocalFSTrajectoryRepository, **overrides) -> str:
    kwargs = dict(
        agent_id="glm-5.2",
        account_id="dataclaw",
        scope="agent",
        owner_space="no_skill",
        trajectory_id="traj_0123456789abcdef",
        idempotency_key="idem-key-1",
        payload=_payload(),
    )
    kwargs.update(overrides)
    return repo.save_bundle(**kwargs)


def test_save_bundle_uses_account_scope_owner_layout(tmp_path: Path) -> None:
    repo = LocalFSTrajectoryRepository(root=str(tmp_path))
    base = Path(_save(repo))
    assert base == (
        tmp_path
        / "accounts/dataclaw/scope/agent/no_skill/memories/trajectories/traj_0123456789abcdef"
    )
    assert {p.name for p in base.iterdir()} == BUNDLE_FILES


def test_save_bundle_writes_meta_and_graph_pointer(tmp_path: Path) -> None:
    repo = LocalFSTrajectoryRepository(root=str(tmp_path))
    base = Path(_save(repo))
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    assert meta["trajectory_id"] == "traj_0123456789abcdef"
    assert meta["task_id"] == "task-a"
    assert meta["labels"] == {"score": 1.0}
    assert meta["owner_space"] == "no_skill"
    assert meta["visualize_graph_png"] is False
    assert meta["saved_at"].endswith("+00:00")
    pointer = json.loads((base / "graph_pointer.json").read_text(encoding="utf-8"))
    assert pointer["backend"] == "localfs_phase1"
    assert pointer["raw_graph_file"] == str(base / "raw_graph.json")
    assert (base / ".abstract.md").read_text(encoding="utf-8") == "L0 text"


def test_indexes_support_lookup_and_replay(tmp_path: Path) -> None:
    repo = LocalFSTrajectoryRepository(root=str(tmp_path))
    base = _save(repo)
    assert repo.find_trajectory_id_by_idempotency_key("idem-key-1") == "traj_0123456789abcdef"
    assert repo.find_trajectory_id_by_idempotency_key("missing") is None

    bundle = repo.load_trajectory("traj_0123456789abcdef")
    assert bundle is not None
    assert bundle["base_path"] == base
    assert bundle["abstract"] == "L0 text"

    uri = "ctx://agent/no_skill/memories/trajectories/traj_0123456789abcdef"
    assert repo.load_trajectory_by_uri(uri)["base_path"] == base
    for name in ("_index.json", "_uri_index.json", "_idempotency.json"):
        assert (tmp_path / name).is_file()


def test_load_missing_trajectory_returns_none(tmp_path: Path) -> None:
    repo = LocalFSTrajectoryRepository(root=str(tmp_path))
    assert repo.load_trajectory("traj_nope") is None
    assert repo.load_trajectory_by_uri("ctx://agent/x/memories/trajectories/traj_nope") is None
