#!/usr/bin/env bash
# Phase A: DataClaw trajs → AMC verify layout → API skill author → export/SKILL.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASELINE_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

if [[ -f "$BASELINE_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$BASELINE_ROOT/.env"
  set +a
  echo "[env] loaded $BASELINE_ROOT/.env"
fi
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  echo "[env] loaded $ROOT/.env"
fi

echo "=== 0/4 deps ==="
python -m pip install -q "openai>=1.0"

NAME_SUBSTR="${NAME_SUBSTR:-20260810}"
CACHE="$ROOT/cache/dataclaw_learn20"
PRED_DIR="$CACHE/da_agent/iter0_sample0"
VERIFY_DIR="$ROOT/outputs/dataclaw_learn20/verifier/iter_0"
SKILL_DIR="$ROOT/outputs/dataclaw_learn20/skill_manager/iter_0/skills"
DATA_DIR="${DATA_DIR:-/home/qchenax/DataClaw/assets/database}"
DRY_RUN="${DRY_RUN:-0}"
USE_SUPERVISED="${USE_SUPERVISED:-0}"
# Optional side step: record the same selected runs into the trajectory store (does not affect Phase A).
RECORD_TRAJ="${RECORD_TRAJ:-0}"
TRAJ_STORE="${TRAJ_STORE:-$ROOT/outputs/trajectory_store}"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "=== 1/4 convert_predictions ==="
python -m dataclaw_bridge.convert_predictions \
  --name-substr "$NAME_SUBSTR" \
  --skill-mode baseline \
  --output-dir "$PRED_DIR"

if [[ "$RECORD_TRAJ" == "1" ]]; then
  echo "=== 1b/4 record_trajectories (optional) ==="
  python -m dataclaw_bridge.record_trajectories \
    --name-substr "$NAME_SUBSTR" \
    --skill-mode baseline \
    --store-root "$TRAJ_STORE" \
    || echo "[warn] record_trajectories failed; continuing Phase A"
fi

echo "=== 2/4 run_verify ==="
VERIFY_ARGS=(--predictions-dir "$PRED_DIR" --workspace "$VERIFY_DIR")
if [[ "$USE_SUPERVISED" == "1" ]]; then
  VERIFY_ARGS+=(--use-supervised)
fi
python -m dataclaw_bridge.run_verify "${VERIFY_ARGS[@]}"

echo "=== 3/4 run_offline_skill_author ==="
AUTHOR_ARGS=(
  --traj-dir "$VERIFY_DIR"
  --skill-output-dir "$SKILL_DIR"
  --data-dir "$DATA_DIR"
)
if [[ "$DRY_RUN" == "1" ]]; then
  AUTHOR_ARGS+=(--dry-run)
fi
python -m dataclaw_bridge.run_offline_skill_author "${AUTHOR_ARGS[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "Dry-run done (no SKILL.md). Re-run without DRY_RUN=1 to call the LLM."
  exit 0
fi

echo "=== 4/4 export_openclaw_skill ==="
python -m dataclaw_bridge.export_openclaw_skill \
  --src "$SKILL_DIR/SKILL.md" \
  --out "$ROOT/export/SKILL.md"

echo
echo "Done. Skill ready at: $ROOT/export/SKILL.md"
echo "Evaluate in DataClaw with:"
echo "  cd /home/qchenax/DataClaw"
echo "  source $BASELINE_ROOT/.env"
echo "  SUITE=\$(tr '\\n' ',' < .tmp/learn_skill_20/task_ids.txt | sed 's/,\$//')"
echo "  python dataclaw/eval/run_batch.py --model \"\$DATACLAW_MODEL\" --suite \"\$SUITE\" \\"
echo "    --skill-path $ROOT/export/SKILL.md"
