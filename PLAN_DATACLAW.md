# Plan: AMC × DataClaw（skill 生成）

> 状态：Phase A bridge 可直接运行；AMC 尚未单独评测（当前代码与原 baseline 相同，来源见 `README.md` 的 Acknowledgement）。  
> 上游：https://github.com/zjunlp/DataMind/tree/main/datacope/general  
> 本地：`~/baseline/amc`（DataMind sparse；可运行包在 `amc/general/`，约 38MB）

---

## 1. AMC 如何生成 skill

AMC General 是面向 **数据分析 agent** 的可配置环（`README.md`、`src/core/loop.py`）：

```text
1. da_agent     — 在任务集上跑 agent（react / claude_code / codex）→ prediction_*.json（含 conversation）
2. verifier     — 按成功/失败（或一致性）整理轨迹目录 success/ / fail/
3. skill_manager— 读 verifier 产出的轨迹 + 数据目录，用 skill-creator 写/改 SKILL.md
可 iterations≥1：注入新 skill 再跑 da_agent → 再 verify → modify
```

三件套：

| 组件 | 作用 |
| --- | --- |
| **da_agent** | 在线解题；产出 `prediction_*.json`（prediction / ground_truth / conversation / turns） |
| **verifier** | `supervised`：用 GT 判对错，每题挑代表成功轨迹 + 最短/最长失败；`agreement`：按答案聚类 |
| **skill_manager** | Claude Code / Codex harness；按 category 或无 category 生成目录技能（`SKILL.md`） |

任务格式（`data/task/{task}/explore.json`）：`query`、`data_files`、可选 `task_id` / `ground_truth` / `metadata.category`。

与已有 baseline 的差别：

| | AMC | SkillX / SkillRevise / Evo… |
| --- | --- | --- |
| 主环 | **在线**跑题 → 验证 → 写 skill | 多从已有轨迹离线抽/改 |
| Skill 作者 | Claude Code / Codex **agent harness** | 多为 OpenAI-compatible 直接生成 |
| 产物 | 分类目录下的 Claude-style `SKILL.md` | 单文件 `dataclaw-workflows` |
| 域 | dabstep 等自带 CSV | DataClaw `./database/` |

---

## 2. 与 DataClaw 的差异

| | AMC 默认 | DataClaw 现状 |
| --- | --- | --- |
| 轨迹 | 环内 `da_agent` 新跑 | 已有 `chat.jsonl` + `score.json` |
| 验证 | supervised 需 `ground_truth` | Acc 已有；生成期可用 gold |
| Skill 写入 | Claude Code / Codex 读盘写 `SKILL.md` | 需单文件 `--skill-path` |
| 数据 | `data/data/{task}/` | `DataClaw/assets/database/` |
| 迭代 refinement | 再跑 agent + modify | 贵；Phase A 不做在线再跑 |

要点：官方 `start.sh` **不能**直接消费 DataClaw `output/`；`skill_manager.agent_type` **仅** `claude_code` / `codex`（无 react）。与本仓库其它 baseline 对齐时，Phase A 应用 **OpenAI-compatible LLM 复用 AMC 提示词** 写 skill（不强制本机 Claude Code），可选保留官方 harness 作对照。

---

## 3. 推荐方案（分阶段）

### Phase A — Offline（优先）

目标：用 learn_skill_20 的 **已有轨迹** 走 AMC 的 verifier 布局 + skill 生成，产出一份可注入 `SKILL.md`；**跳过**在线 `da_agent` 与 refinement 再跑。

1. **固定子集**  
   - Train：`DataClaw/.tmp/learn_skill_20/task_ids.txt`  
   - 轨迹：no-skill `20260810`  
   - Holdout 只用于最终评测  

2. **物化预测**（`dataclaw_bridge/`）  
   - `convert_predictions.py`：每题 → AMC `prediction_*.json`  
     - `prediction` ← score notes / 末轮 assistant（启发式）  
     - `ground_truth` ← qa_gold（**仅生成期**；verifier supervised 需要）  
     - `conversation` ← 由 `chat.jsonl` 压成 role/content 列表  
     - `turns` ← assistant 轮数  
     - `extra_info.query_id` / `category` ← task frontmatter  
     - `extra_info` 里可记 `score`；成功判定可用 DataClaw `score≥1` **或** supervised `question_scorer`  
   - 目录对齐 verifier 输入：  
     `cache/dataclaw_learn20/da_agent/iter0_sample0/prediction_*.json`  

3. **Verifier（复用 upstream）**  
   - 跑 `supervised` →  
     `outputs/.../verifier/…/{query_id}/success|fail/`  
   - 生成期允许用 gold；提示词已要求 skill **勿硬编码答案**（与 Gold 边界一致）  
   - 可选：无 category（整 suite 一份 skill）——与 DataClaw 单文件注入更合；或按 DataClaw `category` 分目录再合并  

4. **Skill 生成（默认：兼容 API 作者）**  
   - **主路径**：`run_offline_skill_author.py`  
     - 复用 `skill_manager/prompt.py` 的 SYSTEM + NO_CATEGORY_CREATE（或按 category）  
     - 将 success/fail 轨迹摘要 + skill-creator 要点 **内联进 prompt**（避免依赖 Claude Code 读盘）  
     - `~/baseline/.env` 的 `OPENAI_COMPATIBLE_*`  
     - 写出 `outputs/.../skills/.../SKILL.md`  
   - **可选对照**：若本机有 Claude Code / Codex，再调官方 `SkillManager`  

5. **导出**  
   - 合并（多 category 时）→ OpenClaw frontmatter `name: dataclaw-workflows` → `export/SKILL.md`  
   - 禁答扫描  

6. **路径**  
   - 包根：`~/baseline/amc/amc/general/`（`pip install -e .`）  
   - Bridge：`~/baseline/amc/dataclaw_bridge/`  
   - 产物：`~/baseline/amc/outputs/dataclaw_learn20/`、`export/SKILL.md`  
   - 评测后：`results/skills/amc/` + `metrics.md`  

### Phase B（可选）

- 用 DataClaw `run_batch --skill-path` 当作 refinement 的「再跑」  
- 官方 Claude Code `SkillManager` 全链路对照  

---

## 4. 实现边界（步骤 3）

**做：**

- `dataclaw_bridge/`：convert predictions / 调 verifier / offline skill author / export / `run_phase_a.sh` / README  
- 复用 `amc/general` 的 supervised verifier + prompts；**不**默认起 react container / Claude Code  
- 读 `~/baseline/.env`  

**不做（除非明确要求）：**

- 改 DataClaw 核心  
- Phase A 静默跑满 LLM  
- 默认在线 `da_agent` 重跑 20 题  
- 强制安装 Claude Code CLI  

---

## 5. 评测计划（步骤 5）

```bash
cd /home/qchenax/DataClaw
source /home/qchenax/baseline/.env
SUITE=$(tr '\n' ',' < .tmp/learn_skill_20/task_ids.txt | sed 's/,$//')
SKILL=/home/qchenax/baseline/amc/export/SKILL.md
python dataclaw/eval/run_batch.py --model "$DATACLAW_MODEL" --suite "$SUITE" --skill-path "$SKILL"
```

---

## 6. 风险与注意

| 风险 | 处理 |
| --- | --- |
| skill_manager 绑 Claude/Codex | Phase A 用 API 作者复用同一套提示；文档标明 degraded vs 官方 harness |
| supervised 要 GT | 生成期用 qa_gold；最终 skill 禁答 |
| 轨迹格式差（OpenClaw vs AMC conversation） | convert 压成通用 role/content；足够 verifier 选样 + LLM 阅读 |
| 多 category vs 单文件 | 默认 **无 category 一份 skill**；需要时再分 category 合并 |
| DataMind 仓库大 | 已 sparse + 删掉 reason/report；只留 `amc/general` |

---

## 7. 下一步

已完成：bridge（Phase A 离线生成链路）。  
待做：本地生成 → learn_skill_20 with-skill 评测 → `results/skills/amc/` + `metrics.md`。  
可选：holdout（`skill_transfer_holdout_20`）、Phase B（refinement / 官方 Claude Code skill_manager 对照）。
