"""Shared helpers for the DataClaw ↔ AMC bridge."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_DATACLAW_ROOT = Path("/home/qchenax/DataClaw")
DEFAULT_TRAIN_IDS = DEFAULT_DATACLAW_ROOT / ".tmp" / "learn_skill_20" / "task_ids.txt"


def repo_root() -> Path:
    """~/baseline/amc"""
    return Path(__file__).resolve().parents[1]


def baseline_root() -> Path:
    return Path(__file__).resolve().parents[2]


def general_root() -> Path:
    """Runnable AMC package: ~/baseline/amc/amc/general"""
    return repo_root() / "amc" / "general"


def ensure_amc_on_path() -> Path:
    """Make `import src.*` work from amc/general."""
    root = general_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def normalize_compat_model_id(model: str, *, base_url: str = "") -> str:
    model = (model or "").strip()
    if not model:
        return model
    url = (base_url or os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or "").lower()
    if "openrouter.ai" in url and model.startswith("openrouter/"):
        return model[len("openrouter/") :]
    return model


def load_dotenv(path: Path, *, override: bool = False) -> bool:
    if not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if override or key not in os.environ or os.environ.get(key, "") == "":
            os.environ[key] = value
    return True


def load_baseline_env(*, override_baseline: bool = True) -> list[Path]:
    loaded: list[Path] = []
    baseline_env = baseline_root() / ".env"
    if load_dotenv(baseline_env, override=override_baseline):
        loaded.append(baseline_env)
    for path in (repo_root() / ".env", general_root() / ".env", DEFAULT_DATACLAW_ROOT / ".env"):
        if load_dotenv(path, override=False):
            loaded.append(path)
    return loaded


def resolve_openai_compat() -> tuple[str, str, str]:
    load_baseline_env()
    base_url = (
        os.environ.get("OPENAI_COMPATIBLE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or ""
    )
    api_key = (
        os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    model = (
        os.environ.get("OPENAI_COMPATIBLE_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ""
    )
    model = normalize_compat_model_id(model, base_url=base_url)
    return base_url, api_key, model


def read_task_ids(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_simple_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'").strip('"')
    return meta, parts[2]


def resolve_gold_path(dataclaw_root: Path, gold_file: str) -> Path | None:
    rel = gold_file.lstrip("./")
    candidates = [
        dataclaw_root / "assets" / rel,
        dataclaw_root / rel,
        dataclaw_root / "assets" / "qa_gold" / Path(rel).name,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_task_gold(dataclaw_root: Path, task_id: str) -> dict[str, Any]:
    tasks_dir = dataclaw_root / "tasks"
    path = tasks_dir / f"{task_id}.md"
    if not path.is_file():
        matches = sorted(tasks_dir.glob(f"{task_id}*.md"))
        if not matches:
            return {}
        path = matches[0]
    meta, body = parse_simple_frontmatter(path.read_text(encoding="utf-8"))
    gold_file = meta.get("gold_file") or ""
    gold: dict[str, Any] = {}
    if gold_file:
        gp = resolve_gold_path(dataclaw_root, gold_file)
        if gp is not None:
            gold = json.loads(gp.read_text(encoding="utf-8"))
    prompt = body
    if "## Prompt" in body:
        prompt = body.split("## Prompt", 1)[1].strip()
        for stop in ("## Rubric", "## Grading", "## Notes"):
            if stop in prompt:
                prompt = prompt.split(stop, 1)[0].strip()
    return {
        "question": gold.get("question") or prompt.split("\n\n")[0],
        "prompt": prompt,
        "ground_truth": str(gold.get("answer") or ""),
        "guidelines": str(gold.get("guidelines") or ""),
        "category": meta.get("category") or meta.get("name") or "dataclaw",
        "gold_file": gold_file,
    }


def select_run_dir(
    task_dir: Path,
    *,
    name_substr: str = "20260810",
    skill_mode: str = "baseline",
) -> Path | None:
    if not task_dir.is_dir():
        return None
    candidates: list[Path] = []
    for child in task_dir.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name_substr and name_substr not in name:
            continue
        is_with_skill = "_with_skill_" in name
        if skill_mode == "baseline" and is_with_skill:
            continue
        if skill_mode == "with_skill" and not is_with_skill:
            continue
        if not (child / "chat.jsonl").is_file():
            continue
        if not (child / "score.json").is_file():
            continue
        candidates.append(child)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda p: (0 if "_with_skill_" in p.name else 1, p.name),
    )[-1]


def _content_parts_to_text(content: Any, *, max_chars: int) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                chunks.append(str(part))
                continue
            ptype = part.get("type")
            if ptype == "text":
                chunks.append(str(part.get("text") or ""))
            elif ptype == "thinking":
                th = str(part.get("thinking") or "").strip()
                if th:
                    chunks.append(f"[thinking] {th[:600]}")
            elif ptype == "toolCall":
                name = part.get("name") or "tool"
                args = part.get("arguments")
                if isinstance(args, dict) and "command" in args:
                    chunks.append(f"{name}: {args.get('command')}")
                else:
                    chunks.append(f"{name}: {json.dumps(args, ensure_ascii=False)}")
            else:
                chunks.append(json.dumps(part, ensure_ascii=False))
        text = "\n".join(c for c in chunks if c)
    else:
        text = str(content)
    text = text.strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 20] + "\n...[truncated]..."
    return text


def chat_jsonl_to_conversation(
    chat_path: Path,
    *,
    max_obs_chars: int = 1500,
    max_msg_chars: int = 3000,
    max_steps: int = 80,
) -> tuple[list[dict[str, Any]], int, str]:
    """Convert OpenClaw chat.jsonl → OpenAI-ish conversation + turns + last assistant."""
    steps: list[dict[str, Any]] = []
    n_assistant = 0
    last_assistant = ""
    pending: list[str] = []

    for line in chat_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message":
            continue
        message = event.get("message") or {}
        role = message.get("role")
        content = message.get("content")

        if role == "user":
            text = _content_parts_to_text(content, max_chars=max_msg_chars)
            if text:
                text = re.sub(r"^\[.*?\]\s*", "", text, count=1)
                steps.append({"role": "user", "content": text})
            continue

        if role == "assistant":
            n_assistant += 1
            texts: list[str] = []
            tool_bits: list[str] = []
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        t = str(part.get("text") or "")
                        if t:
                            texts.append(t)
                    elif ptype == "toolCall":
                        name = part.get("name") or "tool"
                        args = part.get("arguments")
                        if isinstance(args, dict) and "command" in args:
                            cmd = f"{name}: {args.get('command')}"
                        else:
                            cmd = f"{name}: {json.dumps(args, ensure_ascii=False)}"
                        if max_msg_chars > 0 and len(cmd) > max_msg_chars:
                            cmd = cmd[: max_msg_chars - 20] + "...[truncated]"
                        tool_bits.append(cmd)
                        pending.append(cmd)
            else:
                t = _content_parts_to_text(content, max_chars=max_msg_chars)
                if t:
                    texts.append(t)
            joined = "\n".join(texts + [f"[tool_call] {c}" for c in tool_bits]).strip()
            if max_msg_chars > 0 and len(joined) > max_msg_chars:
                joined = joined[: max_msg_chars - 20] + "\n...[truncated]..."
            if joined:
                last_assistant = "\n".join(texts).strip() or joined
                steps.append({"role": "assistant", "content": joined})
            continue

        if role in ("toolResult", "tool"):
            obs = _content_parts_to_text(content, max_chars=max_obs_chars)
            cmd = pending.pop(0) if pending else "(toolResult)"
            steps.append(
                {
                    "role": "user",
                    "content": f"[tool_result] {cmd}\n{obs or '(empty)'}",
                }
            )

    if len(steps) > max_steps:
        head = max_steps // 2
        tail = max_steps - head
        omitted = len(steps) - max_steps
        steps = (
            steps[:head]
            + [{"role": "user", "content": f"[... {omitted} steps truncated ...]"}]
            + steps[-tail:]
        )
    return steps, n_assistant, last_assistant


_AGENT_ANS_RE = re.compile(
    r"(?i)(?:agent\s*answer|predicted|final\s*answer)\s*[:=]\s*(.+?)(?:\n|$)"
)


def extract_predicted_from_notes(notes: str, fallback: str = "") -> str:
    m = _AGENT_ANS_RE.search(notes or "")
    if m:
        return m.group(1).strip()[:800]
    return (fallback or "")[:800]
