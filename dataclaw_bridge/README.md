# AMC × DataClaw bridge (Phase A)

Offline bootstrap: DataClaw `chat.jsonl` + `score.json` → AMC verifier layout →
OpenAI-compatible skill author (AMC prompts) → one OpenClaw `SKILL.md`.

**Skipped**: online `da_agent`, Claude Code / Codex harness, refinement re-runs.

## Layout

| Path | Role |
| --- | --- |
| `convert_predictions.py` | DataClaw → `prediction_*.json` |
| `run_verify.py` | Score-aligned success/fail tree (optional `--use-supervised`) |
| `run_offline_skill_author.py` | API author using AMC SYSTEM + create prompts |
| `export_openclaw_skill.py` | Normalize → `export/SKILL.md` (`name: dataclaw-workflows`) |
| `record_trajectories.py` | Optional: record selected runs as trajectory-store bundles |
| `run_phase_a.sh` | End-to-end |

## Config

`~/baseline/.env`:

- `OPENAI_COMPATIBLE_BASE_URL` / `OPENAI_COMPATIBLE_API_KEY` / `OPENAI_COMPATIBLE_MODEL`
  (OpenRouter model id **without** `openrouter/` prefix)

## Run (you run this)

```bash
cd /home/qchenax/baseline/amc
bash dataclaw_bridge/run_phase_a.sh
```

Optional:

```bash
# Build prompts only (no LLM)
DRY_RUN=1 bash dataclaw_bridge/run_phase_a.sh

# Use upstream SupervisedVerifier string match instead of score labels
USE_SUPERVISED=1 bash dataclaw_bridge/run_phase_a.sh

# Also record the selected runs into the trajectory store (TRAJ_STORE overrides the location)
RECORD_TRAJ=1 bash dataclaw_bridge/run_phase_a.sh
```

Outputs:

- `cache/dataclaw_learn20/da_agent/iter0_sample0/prediction_*.json`
- `outputs/dataclaw_learn20/verifier/iter_0/<task_id>/{success,fail}/`
- `outputs/dataclaw_learn20/skill_manager/iter_0/skills/SKILL.md`
- `export/SKILL.md`
- with `RECORD_TRAJ=1`: `outputs/trajectory_store/` (see [Trajectory store](#trajectory-store))

## Trajectory store

`record_trajectories.py` converts each selected run's `chat.jsonl` into trajectory steps and stores one bundle per run. It uses the same `select_run_dir` as `convert_predictions.py`, so by default it records exactly the runs Phase A uses.

```bash
python -m dataclaw_bridge.record_trajectories \
  --task-ids ~/archive/DA_Workflow/.tmp/learn_skill_20/task_ids.txt \
  --runs-dir ~/archive/DA_Workflow/output
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--name-substr` / `--skill-mode` | `20260810` / `baseline` | Run selection, same as `convert_predictions.py` |
| `--all-runs` | off | Record every run with a `chat.jsonl` under each task |
| `--store-root` | `outputs/trajectory_store` | Bundle root |
| `--agent-id` / `--owner-space` | from run dir name | e.g. `glm-5.2` / `no_skill` or `with_skill` |
| `--force` | off | Rewrite bundles that were already recorded |

Each run prints `[accepted|idempotent|skip|missing|error]`, followed by a summary line. Runs without tool calls are skipped. Labels in `meta.json` include task id, run name, batch, score, success, query, final answer, token usage and `chat_sha256`.

## Eval

```bash
cd /home/qchenax/DataClaw
source /home/qchenax/baseline/.env
SUITE=$(tr '\n' ',' < .tmp/learn_skill_20/task_ids.txt | sed 's/,$//')
python dataclaw/eval/run_batch.py --model "$DATACLAW_MODEL" --suite "$SUITE" \
  --skill-path /home/qchenax/baseline/amc/export/SKILL.md
```

After eval: copy skill to `~/baseline/results/skills/amc/` and update `results/metrics.md`.

## Gold boundary

`qa_gold` / score used only during convert + verify. Trajectory digests sent to the
author redact `ground_truth` / exact predictions. Final `SKILL.md` must not contain
answers or milestone gold. Trajectory bundles store only the numeric score and success
flag from `score.json`; its `notes` (which can quote the gold answer) are never recorded.
