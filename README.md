<h1 align="center"> AMC </h1>

**AMC** generates reusable skills for data-analysis agents from agent trajectories. It runs a verifier over trajectories to separate successful and failed attempts, then has a skill manager distill them into a `SKILL.md` that can be injected into the agent.

AMC also includes a **trajectory store** that records each trajectory as a self-contained bundle (normalized steps, an action dependency graph, and short summaries) on the local filesystem, so runs can be replayed and analyzed later.

## Layout

| Path | Role |
| --- | --- |
| [`amc/`](amc/README.md) | AMC framework: `general/` (configurable loop) and `report_task/` (report-style pipeline) |
| [`amc/general/src/trajectory_store/`](amc/README.md#trajectory-store) | Trajectory store: transcript adapters, graph/summary builder, LocalFS bundles |
| [`dataclaw_bridge/`](dataclaw_bridge/README.md) | Offline pipeline: DataClaw `chat.jsonl` + `score.json` → verifier layout → skill author → `export/SKILL.md`; optional trajectory recording |
| [`PLAN_DATACLAW.md`](PLAN_DATACLAW.md) | How AMC is adapted to DataClaw trajectories and evaluated |

## Quick start (DataClaw)

```bash
cd /home/qchenax/baseline/amc
bash dataclaw_bridge/run_phase_a.sh        # writes export/SKILL.md
```

API settings are read from `~/baseline/.env` (`OPENAI_COMPATIBLE_*`). Evaluation commands are in [`dataclaw_bridge/README.md`](dataclaw_bridge/README.md#eval).

## Trajectory store

Record DataClaw runs as trajectory bundles, either standalone or as an optional step of Phase A:

```bash
cd /home/qchenax/baseline/amc

# Standalone: same run selection as Phase A (one run per task by default)
python -m dataclaw_bridge.record_trajectories \
  --task-ids <task_ids.txt> --runs-dir <DataClaw output dir> \
  [--all-runs] [--store-root outputs/trajectory_store]

# Inside Phase A (off by default; a recording failure does not stop Phase A)
RECORD_TRAJ=1 bash dataclaw_bridge/run_phase_a.sh
```

Each run becomes one bundle under `outputs/trajectory_store/accounts/<account>/scope/agent/<owner_space>/memories/trajectories/<trajectory_id>/`, containing `trajectory.json`, `raw_graph.json`, `clean_graph.json`, `.abstract.md`, `.overview.md` and `meta.json`. Re-recording the same trajectory is a no-op. Bundles never contain gold answers or grader notes. Details are in [`amc/README.md`](amc/README.md#trajectory-store).
