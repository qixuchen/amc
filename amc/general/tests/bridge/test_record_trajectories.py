from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dataclaw_bridge.common import load_task_gold, select_run_dir
from dataclaw_bridge.record_trajectories import main, parse_run_name

from chat_fixtures import assistant, simple_run_events, text, user, write_chat

pytestmark = pytest.mark.unit

GOLD_ONLY = "gold answer 0.67"


def _make_run(task_dir: Path, name: str, events: list, *, score: float = 0.0, usage: bool = True) -> Path:
    run = task_dir / name
    write_chat(run / "chat.jsonl", events)
    (run / "score.json").write_text(
        json.dumps({"task_id": task_dir.name, "score": score, "max_score": 1.0, "notes": f"Agent differs from {GOLD_ONLY}."}),
        encoding="utf-8",
    )
    if usage:
        (run / "usage.json").write_text(
            json.dumps({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "request_count": 2, "elapsed_time": 9.5}),
            encoding="utf-8",
        )
    return run


@pytest.fixture
def dataclaw_tree(tmp_path: Path) -> dict[str, Path]:
    runs = tmp_path / "output"
    t1 = runs / "task_001_a"
    # OpenClaw tool-call ids are unique per run, which keeps per-run content hashes distinct.
    _make_run(t1, "glm-5.2_20260807_1633_aaaaaa", simple_run_events("old", call_id="call_a"))
    _make_run(t1, "glm-5.2_20260810_0936_bbbbbb", simple_run_events("Zhejiang 0.71", call_id="call_b"), score=1.0)
    _make_run(t1, "glm-5.2_with_skill_20260810_1046_cccccc", simple_run_events("with skill", call_id="call_c"))
    t2 = runs / "task_002_b"
    _make_run(t2, "glm-5.2_20260810_0936_dddddd", [user("q"), assistant(text("no tools"), stop="stop")])
    ids = tmp_path / "task_ids.txt"
    ids.write_text("task_001_a\ntask_002_b\ntask_003_missing\n", encoding="utf-8")
    return {"runs": runs, "ids": ids, "store": tmp_path / "store"}


def _run(tree: dict[str, Path], *extra: str) -> int:
    return main(
        [
            "--task-ids", str(tree["ids"]),
            "--runs-dir", str(tree["runs"]),
            "--store-root", str(tree["store"]),
            *extra,
        ]
    )


def _bundles(store: Path) -> list[Path]:
    return sorted(p.parent for p in store.glob("accounts/*/scope/*/*/memories/trajectories/*/meta.json"))


def _meta(bundle: Path) -> dict:
    return json.loads((bundle / "meta.json").read_text(encoding="utf-8"))


def test_parse_run_name() -> None:
    assert parse_run_name("glm-5.2_20260810_0936_c56871") == {
        "agent_id": "glm-5.2",
        "skill_mode": "baseline",
        "batch": "20260810_0936",
    }
    assert parse_run_name("glm-5.2_with_skill_20260818_1638_4a5e6c")["skill_mode"] == "with_skill"
    assert parse_run_name("weird-name")["agent_id"] == "weird-name"


def test_records_exactly_the_phase_a_selection(dataclaw_tree) -> None:
    assert _run(dataclaw_tree) == 0
    bundles = _bundles(dataclaw_tree["store"])
    assert len(bundles) == 1
    meta = _meta(bundles[0])
    selected = select_run_dir(dataclaw_tree["runs"] / "task_001_a", name_substr="20260810", skill_mode="baseline")
    assert meta["labels"]["run_name"] == selected.name
    assert meta["task_id"] == "task_001_a"
    assert meta["agent_id"] == "glm-5.2"
    assert meta["owner_space"] == "no_skill"
    assert "/accounts/dataclaw/scope/agent/no_skill/" in str(bundles[0])


def test_labels_content(dataclaw_tree) -> None:
    _run(dataclaw_tree)
    labels = _meta(_bundles(dataclaw_tree["store"])[0])["labels"]
    assert labels["score"] == 1.0 and labels["success"] is True
    assert labels["skill_mode"] == "baseline"
    assert labels["batch"] == "20260810_0936"
    assert labels["query"] == "Which province ranks first?"
    assert labels["final_response"] == "Zhejiang 0.71"
    assert labels["usage"]["total_tokens"] == 120
    assert len(labels["chat_sha256"]) == 64
    assert labels["converter"] == "openclaw_chat/1"
    assert labels["conversion_stats"]["tool_calls"] == 1


def test_gold_material_is_not_recorded(dataclaw_tree) -> None:
    _run(dataclaw_tree, "--all-runs")
    store = dataclaw_tree["store"]
    for path in store.rglob("*"):
        if path.is_file():
            assert GOLD_ONLY not in path.read_text(encoding="utf-8"), path
    for bundle in _bundles(store):
        assert not {"notes", "score_notes", "ground_truth", "gold"} & set(_meta(bundle)["labels"])


def test_rerun_is_idempotent(dataclaw_tree, capsys) -> None:
    _run(dataclaw_tree)
    before = _bundles(dataclaw_tree["store"])
    capsys.readouterr()
    assert _run(dataclaw_tree) == 0
    out = capsys.readouterr().out
    assert "[idempotent] task_001_a" in out
    assert _bundles(dataclaw_tree["store"]) == before


def test_skips_and_missing_are_reported(dataclaw_tree, capsys) -> None:
    _run(dataclaw_tree)
    out = capsys.readouterr().out
    assert "[skip] task_002_b" in out and "no tool calls" in out
    assert "[missing] task_003_missing" in out
    assert "accepted=1 idempotent=0 skipped=1 missing=1 errors=0" in out


def test_all_runs_records_every_run_with_owner_space_by_mode(dataclaw_tree) -> None:
    _run(dataclaw_tree, "--all-runs")
    owners = sorted(_meta(b)["owner_space"] for b in _bundles(dataclaw_tree["store"]))
    assert owners == ["no_skill", "no_skill", "with_skill"]


def test_owner_space_and_agent_overrides(dataclaw_tree) -> None:
    _run(dataclaw_tree, "--owner-space", "amc", "--agent-id", "custom-agent")
    meta = _meta(_bundles(dataclaw_tree["store"])[0])
    assert meta["owner_space"] == "amc"
    assert meta["agent_id"] == "custom-agent"


def test_writes_only_under_store_root(dataclaw_tree, tmp_path: Path) -> None:
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    _run(dataclaw_tree, "--all-runs")
    new_files = {p for p in tmp_path.rglob("*") if p.is_file()} - before
    assert new_files
    assert all(dataclaw_tree["store"] in p.parents for p in new_files)


def test_limit(dataclaw_tree, capsys) -> None:
    _run(dataclaw_tree, "--limit", "1")
    assert "accepted=1 idempotent=0 skipped=0 missing=0 errors=0" in capsys.readouterr().out


ARCHIVE_ROOT = Path(os.environ.get("DATACLAW_ARCHIVE_ROOT", Path.home() / "archive/DA_Workflow"))


def test_real_learn_skill_20_batch(tmp_path: Path, capsys) -> None:
    ids = ARCHIVE_ROOT / ".tmp/learn_skill_20/task_ids.txt"
    if not ids.is_file():
        pytest.skip(f"DataClaw archive not found at {ARCHIVE_ROOT}")
    store = tmp_path / "store"
    runs_dir = ARCHIVE_ROOT / "output"
    argv = ["--task-ids", str(ids), "--runs-dir", str(runs_dir), "--store-root", str(store)]
    expected = sorted(
        run.name
        for tid in ids.read_text(encoding="utf-8").split()
        if (run := select_run_dir(runs_dir / tid, name_substr="20260810", skill_mode="baseline")) is not None
    )
    assert main(argv) == 0
    first = capsys.readouterr().out
    bundles = _bundles(store)
    assert sorted(_meta(b)["labels"]["run_name"] for b in bundles) == expected, first

    for bundle in bundles:
        meta = _meta(bundle)
        gold = load_task_gold(ARCHIVE_ROOT, meta["task_id"]).get("ground_truth") or ""
        if len(gold) < 3:
            continue
        chat = (Path(meta["labels"]["run_dir"]) / "chat.jsonl").read_text(encoding="utf-8")
        for path in bundle.rglob("*"):
            if path.is_file() and gold in path.read_text(encoding="utf-8"):
                assert gold in chat, f"{path} contains gold text not present in the agent trajectory"

    assert main(argv) == 0
    assert f"accepted=0 idempotent={len(expected)}" in capsys.readouterr().out
