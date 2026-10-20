<h1 align="center"> AMC </h1>

## Table of Contents

- 👀 [Overview](#overview)
- 🔧 [Installation](#installation)
- 📦 [Data](#data)
- 💻 [Running AMC General Framework](#running-amc-general-framework)
- 🗂️ [Trajectory Store](#trajectory-store)
- 📝 [Running Report-Style Tasks](#running-report-style-tasks)
- 🧠 [Running Reasoning-Style Tasks](#running-reasoning-style-tasks)
- 🙏 [Acknowledgements](#acknowledgements)

---

## 👀 Overview

**AMC** is an unsupervised verifier-guided framework for discovering reusable skills for data-analytic agents.

Instead of updating model parameters or relying on costly human supervision, AMC improves agents at inference time by distilling procedural skills from unlabeled exploration trajectories. It coordinates three components: a **Data-Analytic Agent** that generates trajectories, an **Unsupervised Verifier** that extracts quality signals, and a **Skill Manager** that turns contrastive trajectory feedback into reusable skills.

AMC supports both major data-analysis formats:

* **Report-style analysis**: uses an Adaptive Checklist Verifier to derive task-specific evaluation criteria and score reports by verifiable coverage.
* **Reasoning-style analysis**: uses an Answer Agreement Verifier to cluster trajectories by answer agreement and estimate reliability through self-consistency.

We evaluate AMC on **Deep Data Research** and **DABStep**. Across four model settings, AMC consistently improves held-out performance, achieving average gains of 9.71% on report-style tasks and 32.30% on reasoning-style tasks.

<p align="center">
  <img src="figs/framework.png" alt="Overview of the AMC framework." width="95%">
</p>


## 🔧 Installation

This repository contains three related code paths:

- `general/`: a configurable AMC loop for custom data-analysis tasks.
- `report_task/`: the report-style task implementation in paper based on DDR-Bench and Deep Data Research.
- `reason_task/`: the reasoning-style task implementation in paper  based on DABStep and DSGym.

### 📋 Prerequisites

- Python 3.10 or newer for `general/` and `report_task/`.
- Python 3.12 or newer is recommended for `reason_task/`.
- Docker or a local DSGym-compatible executor manager when using ReAct/DSGym execution.
- Claude Code or Codex if you use those agent harnesses.
- API access to the model provider used by the data-analysis agent, verifier, evaluator, or skill manager.

### ⚙️ Environment Setup

Each subproject maintains its own dependency and runtime instructions:

- General AMC framework: [general/README.md](general/README.md)
- Report-style task experiments: [report_task/README.md](report_task/README.md)
- Reasoning-style task experiments: [reason_task/README.md](reason_task/README.md)

If you use Claude Code or Codex, install and authenticate the corresponding CLI before running those harnesses:

```bash
# Claude Code
curl -fsSL https://claude.ai/install.sh | bash
claude

# Codex
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex login
```

### 🐳 Execution Environment

The ReAct-style agent use a DSGym-style executor manager at `http://localhost:5005`. See [general/README.md](general/README.md) and [reason_task/README.md](reason_task/README.md) for the concrete executor setup. Agents such as `codex` and `claude_code` may not need the executor manager, depending on the selected runtime and task.

## 📦 Data

Data preparation is task-specific:

- `general/` expects paired task and data directories under `general/data/`; see [general/README.md](general/README.md).
- `report_task/` supports the 10-K, MIMIC, and GLOBEM report-style scenarios; see [report_task/README.md](report_task/README.md).
- `reason_task/` uses DABStep data in its DSGym directories; see [reason_task/README.md](reason_task/README.md).

## 💻 Running AMC General Framework

`general/` is the reusable AMC pipeline for custom data-analysis tasks. It supports configurable task loaders, agent harnesses, verifiers, skill managers, iterative skill refinement, and resume controls.

For setup, task format, configuration fields, and CLI usage, see [general/README.md](general/README.md).

## 🗂️ Trajectory Store

`general/src/trajectory_store/` records agent trajectories as self-contained bundles on the local filesystem. Recording is a side step: it reads trajectories and writes to its own directory, and does not change which trajectories the verifier or skill manager use.

For each trajectory it:

1. validates and normalizes the steps (`AIMessage` / `ToolMessage` pairs; long tool outputs truncated to 12,000 characters);
2. builds a **raw graph** of actions with dataflow, retry and temporal dependencies, and a **clean graph** with superseded failed attempts removed;
3. writes an L0 one-line abstract and an L1 overview (rule-based by default; an LLM summarizer or dataflow extractor can be injected);
4. saves the bundle with a content-addressed `trajectory_id` and updates the `_index.json`, `_uri_index.json` and `_idempotency.json` indexes, so re-recording the same trajectory is a no-op. Every attempt is appended to `_audit.jsonl`.

Bundle layout:

```text
<store_root>/accounts/<account>/scope/<scope>/<owner_space>/memories/trajectories/<trajectory_id>/
├── trajectory.json     # normalized steps
├── raw_graph.json
├── clean_graph.json
├── graph_pointer.json
├── .abstract.md        # L0
├── .overview.md        # L1
└── meta.json           # task id, labels, node/edge counts
```

Python API:

```python
from src.trajectory_store import TrajectoryRecorder
from src.trajectory_store.adapters.openclaw_chat import convert_chat_jsonl

conv = convert_chat_jsonl("path/to/chat.jsonl")      # OpenClaw transcript -> steps
recorder = TrajectoryRecorder(root="outputs/trajectory_store", account_id="dataclaw", agent_id="glm-5.2")
result = recorder.record(steps=conv.steps, session_id="run-1", task_id="task_008", labels={"query": conv.query})
print(result.status, result.trajectory_id, result.base_path)
```

The OpenClaw adapter pairs each tool call with its result by `toolCallId`, so parallel tool calls stay correctly matched. For DataClaw runs, `dataclaw_bridge/record_trajectories.py` selects runs, converts them and stores score, usage and the final answer as labels. Gold answers and grader notes are never written. Tests are in `general/tests/` (`cd general && python -m pytest tests -q`).

## 📝 Running Report-Style Tasks

`report_task/` contains the AMC report-style pipeline and the DDR-Bench runner/evaluator for Deep Data Research tasks. It covers skill generation, agent execution with or without skills, and LLM-as-checker evaluation.

Pre-generated skills from the paper experiments are available under [report_task/skill](report_task/skill).

For data preparation, configuration, skill generation, agent runs, and evaluation commands, see [report_task/README.md](report_task/README.md).

## 🧠 Running Reasoning-Style Tasks

`reason_task/` contains the AMC reasoning-style pipeline for DABStep. It has two stages: skill generation on the explore split and skill evaluation on the test split.

The provided reasoning-task skills are organized as:

```text
reason_task/eval/skill/
├── 0/iter0 ... iter2/
├── 1/iter0 ... iter2/
└── 2/iter0 ... iter2/
```

For environment setup, DABStep data placement, generation commands, and evaluation commands, see [reason_task/README.md](reason_task/README.md). The generation and evaluation subpipelines also have detailed READMEs: [reason_task/generation/README.md](reason_task/generation/README.md) and [reason_task/eval/README.md](reason_task/eval/README.md).

## 🙏 Acknowledgements

Part of the code in this repository is based on [DataCOPE](https://github.com/zjunlp/DataMind/tree/main/datacope) from the [DataMind](https://github.com/zjunlp/DataMind) project. The evaluation results quoted in the Overview are reported in the DataCOPE paper. If you use this code, please cite:

```bibtex
@misc{qiu2026unsupervisedskilldiscovery,
      title={Unsupervised Skill Discovery for Agentic Data Analysis},
      author={Zhisong Qiu and Kangqi Song and Shengwei Tang and Shuofei Qiao and Lei Liang and Huajun Chen and Shumin Deng},
      year={2026},
      eprint={2606.06416},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2606.06416},
}
```

We also thank, as the original DataCOPE authors did, the [DSGym](https://github.com/fannie1208/DSGym) team for the data-analysis evaluation framework used by the reasoning-style task pipeline, and the authors of [DDR_Bench](https://github.com/thinkwee/DDR_Bench) for releasing benchmark resources and task settings for report-style data analysis.
