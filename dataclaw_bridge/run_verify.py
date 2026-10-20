#!/usr/bin/env python3
"""Organize converted predictions into AMC verifier layout.

Default: score-aligned organizer (DataClaw score≥1), same tree as supervised:
  <workspace>/<query_id>/success/prediction_*.json
  <workspace>/<query_id>/fail/prediction_*.json
  <workspace>/<query_id>/summary.json

Optional: --use-supervised calls upstream SupervisedVerifier.init_run().
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .common import ensure_amc_on_path, write_json


def organize_by_score(predictions_dir: Path, workspace: Path) -> dict:
    """Mirror supervised no-category layout using DataClaw score labels."""
    if workspace.exists():
        for child in workspace.iterdir():
            if child.is_dir() and child.name not in (".", ".."):
                shutil.rmtree(child)
            elif child.is_file() and child.name.endswith(".json"):
                child.unlink()

    workspace.mkdir(parents=True, exist_ok=True)
    n_ok = n_fail = 0
    for path in sorted(predictions_dir.glob("prediction_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        extra = data.get("extra_info") or {}
        query_id = str(extra.get("query_id") or data.get("instance_id") or path.stem)
        success = bool(extra.get("dataclaw_success"))
        if "score" in extra and not success:
            success = float(extra["score"]) >= 1.0

        query_dir = workspace / query_id
        group = "success" if success else "fail"
        dest_dir = query_dir / group
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Match supervised: drop extra_info / token_usage from published traj copy
        published = {k: v for k, v in data.items() if k not in ("extra_info", "token_usage")}
        # Keep a lean label file for the author; redaction happens at author time
        dest = dest_dir / f"{path.stem}_0_score_label.json"
        write_json(dest, published)

        summary = {
            "query_id": query_id,
            "total_samples": 1,
            "success_count": 1 if success else 0,
            "fail_count": 0 if success else 1,
            "accuracy": 1.0 if success else 0.0,
            "label_source": "dataclaw_score",
        }
        write_json(query_dir / "summary.json", summary)
        if success:
            n_ok += 1
        else:
            n_fail += 1

    out = {
        "mode": "score_labels",
        "success": n_ok,
        "fail": n_fail,
        "traj_dir": str(workspace),
        "prompt_key": "VERIFIER_INIT_PROMPT",
    }
    write_json(workspace / "verify_summary.json", out)
    return out


def run_supervised(predictions_dir: Path, workspace: Path) -> dict:
    ensure_amc_on_path()
    from src.verifier.instances.supervised_verifier import (  # type: ignore
        VERIFIER_INIT_PROMPT,
        SupervisedVerifier,
    )

    workspace.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        for child in list(workspace.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)

    verifier = SupervisedVerifier(
        input_file_dirs=[str(predictions_dir)],
        output_dir=str(workspace),
        category_list=[],
    )
    result = verifier.init_run() or {}
    n_ok = len(list(workspace.rglob("success/prediction_*.json")))
    n_fail = len(list(workspace.rglob("fail/prediction_*.json")))
    out = {
        "mode": "supervised",
        "success_files": n_ok,
        "fail_files": n_fail,
        "traj_dir": result.get("traj_dir") or str(workspace),
        "prompt": result.get("prompt") or VERIFIER_INIT_PROMPT,
    }
    write_json(workspace / "verify_summary.json", out)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions-dir", type=Path, required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument(
        "--use-supervised",
        action="store_true",
        help="Call AMC SupervisedVerifier instead of score organizer",
    )
    args = p.parse_args(argv)

    if not args.predictions_dir.is_dir():
        print(f"[error] missing predictions dir: {args.predictions_dir}", file=sys.stderr)
        return 1

    if args.use_supervised:
        summary = run_supervised(args.predictions_dir, args.workspace)
    else:
        summary = organize_by_score(args.predictions_dir, args.workspace)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
