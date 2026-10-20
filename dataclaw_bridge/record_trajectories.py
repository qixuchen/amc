#!/usr/bin/env python3
"""Record DataClaw chat.jsonl trajectories as trajectory-store bundles.

Side-effect only: picks runs with the same `select_run_dir` as convert_predictions
and writes under --store-root; no Phase A output is touched.

Usage:
  python -m dataclaw_bridge.record_trajectories \\
    --task-ids ~/archive/DA_Workflow/.tmp/learn_skill_20/task_ids.txt \\
    --runs-dir ~/archive/DA_Workflow/output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .common import (
    DEFAULT_DATACLAW_ROOT,
    DEFAULT_TRAIN_IDS,
    ensure_amc_on_path,
    read_task_ids,
    repo_root,
    select_run_dir,
)

ensure_amc_on_path()

from src.trajectory_store import TrajectoryRecorder  # noqa: E402
from src.trajectory_store.adapters.openclaw_chat import CONVERTER_ID, convert_chat_jsonl  # noqa: E402

DEFAULT_STORE_ROOT = repo_root() / "outputs" / "trajectory_store"

_RUN_NAME_RE = re.compile(r"^(?P<agent>.+?)(?P<with_skill>_with_skill)?_(?P<date>\d{8})_(?P<hhmm>\d{4})_[0-9a-f]+$")

# score.json "notes" can quote the gold answer, so only numeric fields are copied.
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost_usd",
    "request_count",
    "elapsed_time",
)


def parse_run_name(name: str) -> dict[str, str]:
    m = _RUN_NAME_RE.match(name)
    if not m:
        return {"agent_id": name, "skill_mode": "with_skill" if "_with_skill_" in name else "baseline", "batch": ""}
    return {
        "agent_id": m.group("agent"),
        "skill_mode": "with_skill" if m.group("with_skill") else "baseline",
        "batch": f"{m.group('date')}_{m.group('hhmm')}",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def list_run_dirs(task_dir: Path, *, name_substr: str, skill_mode: str, all_runs: bool) -> list[Path]:
    if not all_runs:
        selected = select_run_dir(task_dir, name_substr=name_substr, skill_mode=skill_mode)
        return [selected] if selected is not None else []
    if not task_dir.is_dir():
        return []
    return sorted(p for p in task_dir.iterdir() if p.is_dir() and (p / "chat.jsonl").is_file())


def build_labels(task_id: str, run_dir: Path, conv: Any, run_info: dict[str, str]) -> dict[str, Any]:
    score_obj = _read_json(run_dir / "score.json")
    score = score_obj.get("score")
    score = float(score) if isinstance(score, (int, float)) else None
    usage = _read_json(run_dir / "usage.json")
    labels: dict[str, Any] = {
        "source": "dataclaw",
        "task_id": task_id,
        "run_name": run_dir.name,
        "run_dir": str(run_dir.resolve()),
        "batch": run_info["batch"],
        "skill_mode": run_info["skill_mode"],
        "score": score,
        "success": score is not None and score >= 1.0,
        "query": conv.query,
        "final_response": conv.final_response,
        "chat_sha256": hashlib.sha256((run_dir / "chat.jsonl").read_bytes()).hexdigest(),
        "converter": CONVERTER_ID,
        "conversion_stats": dict(conv.stats),
    }
    if usage:
        labels["usage"] = {k: usage[k] for k in _USAGE_KEYS if k in usage}
    return labels


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task-ids", type=Path, default=DEFAULT_TRAIN_IDS)
    p.add_argument("--runs-dir", type=Path, default=DEFAULT_DATACLAW_ROOT / "output")
    p.add_argument("--name-substr", default="20260810")
    p.add_argument("--skill-mode", choices=("baseline", "with_skill", "any"), default="baseline")
    p.add_argument("--all-runs", action="store_true", help="Record every run with chat.jsonl under each task")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--store-root", type=Path, default=DEFAULT_STORE_ROOT)
    p.add_argument("--account-id", default="dataclaw")
    p.add_argument("--agent-id", default=None, help="Default: model prefix of the run dir name")
    p.add_argument("--owner-space", default=None, help="Default: no_skill / with_skill from the run dir name")
    p.add_argument("--force", action="store_true", help="Rewrite bundles even if already recorded")
    args = p.parse_args(argv)

    task_ids = read_task_ids(args.task_ids)
    if args.limit > 0:
        task_ids = task_ids[: args.limit]

    recorders: dict[str, TrajectoryRecorder] = {}
    counts = {"accepted": 0, "idempotent": 0, "skipped": 0, "missing": 0, "errors": 0}
    for task_id in task_ids:
        run_dirs = list_run_dirs(
            args.runs_dir / task_id,
            name_substr=args.name_substr,
            skill_mode=args.skill_mode,
            all_runs=args.all_runs,
        )
        if not run_dirs:
            print(f"[missing] {task_id}: no matching run")
            counts["missing"] += 1
            continue
        for run_dir in run_dirs:
            try:
                conv = convert_chat_jsonl(run_dir / "chat.jsonl")
                if not conv.steps:
                    print(f"[skip] {task_id} {run_dir.name}: no tool calls")
                    counts["skipped"] += 1
                    continue
                run_info = parse_run_name(run_dir.name)
                agent_id = args.agent_id or run_info["agent_id"]
                recorder = recorders.get(agent_id)
                if recorder is None:
                    recorder = TrajectoryRecorder(root=args.store_root, account_id=args.account_id, agent_id=agent_id)
                    recorders[agent_id] = recorder
                owner_space = args.owner_space or ("with_skill" if run_info["skill_mode"] == "with_skill" else "no_skill")
                res = recorder.record(
                    steps=conv.steps,
                    session_id=run_dir.name,
                    task_id=task_id,
                    labels=build_labels(task_id, run_dir, conv, run_info),
                    owner_space=owner_space,
                    force=args.force,
                )
            except Exception as exc:
                print(f"[error] {task_id} {run_dir.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                counts["errors"] += 1
                continue
            counts[res.status] += 1
            print(f"[{res.status}] {task_id} {run_dir.name} {res.trajectory_id} nodes={res.nodes} edges={res.edges}")

    print(" ".join(f"{k}={v}" for k, v in counts.items()) + f" -> {args.store_root}")
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
