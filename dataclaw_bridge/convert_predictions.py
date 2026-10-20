#!/usr/bin/env python3
"""Convert DataClaw train trajectories into AMC prediction_*.json files.

For each task:
  - load gold (question / ground_truth) as supervised signals for generation
  - load chat.jsonl → conversation steps
  - use score.json as success label: if score>=1, set prediction=ground_truth
    so SupervisedVerifier aligns with DataClaw grading (answer-format mismatch safe)

Usage:
  python -m dataclaw_bridge.convert_predictions \\
    --output-dir ./work/predictions \\
    --runs-dir /home/qchenax/DataClaw/output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import (
    DEFAULT_DATACLAW_ROOT,
    DEFAULT_TRAIN_IDS,
    chat_jsonl_to_conversation,
    extract_predicted_from_notes,
    load_task_gold,
    read_task_ids,
    select_run_dir,
    write_json,
)


def build_prediction(
    *,
    task_id: str,
    run_dir: Path,
    dataclaw_root: Path,
    max_obs_chars: int,
    max_msg_chars: int,
    max_steps: int,
) -> dict:
    gold = load_task_gold(dataclaw_root, task_id)
    score_obj = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    score = float(score_obj.get("score") or 0.0)
    notes = str(score_obj.get("notes") or "")
    success = score >= 1.0

    conversation, n_turns, last_assistant = chat_jsonl_to_conversation(
        run_dir / "chat.jsonl",
        max_obs_chars=max_obs_chars,
        max_msg_chars=max_msg_chars,
        max_steps=max_steps,
    )
    agent_pred = extract_predicted_from_notes(notes, fallback=last_assistant)
    ground_truth = gold.get("ground_truth") or ""

    # Align supervised verifier with DataClaw score labels.
    if success and ground_truth:
        prediction = ground_truth
    elif agent_pred:
        prediction = agent_pred
    else:
        prediction = "INCORRECT"

    # SupervisedVerifier requires extra_info.query_id (+ optional category).
    return {
        "instance_id": task_id,
        "question": gold.get("question") or gold.get("prompt") or task_id,
        "prompt": gold.get("prompt") or "",
        "prediction": prediction,
        "ground_truth": ground_truth,
        "guidelines": gold.get("guidelines") or "",
        "category": "dataclaw",
        "turns": n_turns,
        "conversation": conversation,
        "messages": conversation,
        "extra_info": {
            "query_id": task_id,
            "task_id": task_id,
            "category": "",  # empty → no-category skill path
            "run_dir": str(run_dir),
            "score": score,
            "score_notes": notes[:2000],
            "agent_prediction": agent_pred,
            "n_assistant_turns": n_turns,
            "dataclaw_success": success,
            "gold_file": gold.get("gold_file") or "",
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--task-ids",
        type=Path,
        default=DEFAULT_TRAIN_IDS,
        help="Newline-separated task ids (default: learn_skill_20)",
    )
    p.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_DATACLAW_ROOT / "output",
        help="Parent of per-task run dirs (DataClaw/output/<task_id>/…)",
    )
    p.add_argument(
        "--dataclaw-root",
        type=Path,
        default=DEFAULT_DATACLAW_ROOT,
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for prediction_<task_id>.json",
    )
    p.add_argument("--name-substr", default="20260810")
    p.add_argument(
        "--skill-mode",
        choices=("baseline", "with_skill", "any"),
        default="baseline",
    )
    p.add_argument("--max-obs-chars", type=int, default=1500)
    p.add_argument("--max-msg-chars", type=int, default=3000)
    p.add_argument("--max-steps", type=int, default=80)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    task_ids = read_task_ids(args.task_ids)
    if args.limit > 0:
        task_ids = task_ids[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    missing = 0
    for tid in task_ids:
        run_dir = select_run_dir(
            args.runs_dir / tid,
            name_substr=args.name_substr,
            skill_mode=args.skill_mode,
        )
        if run_dir is None:
            print(f"[skip] no run for {tid}", file=sys.stderr)
            missing += 1
            continue
        pred = build_prediction(
            task_id=tid,
            run_dir=run_dir,
            dataclaw_root=args.dataclaw_root,
            max_obs_chars=args.max_obs_chars,
            max_msg_chars=args.max_msg_chars,
            max_steps=args.max_steps,
        )
        out = args.output_dir / f"prediction_{tid}.json"
        write_json(out, pred)
        label = "ok" if pred["extra_info"]["dataclaw_success"] else "fail"
        print(f"[write] {out.name} score={pred['extra_info']['score']} ({label})")
        ok += 1

    print(f"done: wrote={ok} missing={missing} → {args.output_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
