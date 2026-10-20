#!/usr/bin/env python3
"""Offline AMC skill author (OpenAI-compatible; no Claude Code / Codex).

Reuses SYSTEM_PROMPT + NO_CATEGORY_SKILL_CREATE_PROMPT + VERIFIER_INIT_PROMPT
from amc/general, but inlines trajectory digests + skill-creator guidance
so a single chat completion can write SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .common import (
    ensure_amc_on_path,
    general_root,
    load_baseline_env,
    resolve_openai_compat,
    write_json,
)

DEFAULT_DATA_DIR = Path("/home/qchenax/DataClaw/assets/database")

OUTPUT_CONTRACT = """
# Output contract (API author — no filesystem agent)

You cannot browse disks or run skill-creator scripts. Instead:

1. Read the inlined skill-creator guidance and verifier instructions below.
2. Analyze the success / fail trajectory digests.
3. Write ONE complete `SKILL.md` for DataClaw-style local CSV / file analysis.
4. Return ONLY the markdown file contents, starting with YAML frontmatter:

```yaml
---
name: dataclaw-workflows
description: <one-line description of when to use this skill>
---
```

Constraints (hard):
- Do NOT hard-code task answers, gold values, specific numeric results, or
  row-level facts that only apply to one exploration task.
- Prefer reusable procedures: explore `./database/`, schema checks, joins,
  aggregations, verification steps, common failure modes.
- Keep body under ~500 lines; be concrete but transferable.
- Adapt tool names to shell / python / pandas / grep style agents.
"""


def _load_amc_prompts() -> tuple[str, str, str]:
    ensure_amc_on_path()
    from src.skill_manager.prompt import (  # type: ignore
        NO_CATEGORY_SKILL_CREATE_PROMPT,
        SYSTEM_PROMPT,
    )
    from src.verifier.instances.supervised_verifier import (  # type: ignore
        VERIFIER_INIT_PROMPT,
    )
    return SYSTEM_PROMPT, NO_CATEGORY_SKILL_CREATE_PROMPT, VERIFIER_INIT_PROMPT


def _skill_creator_digest(max_chars: int = 12000) -> str:
    path = general_root() / "skills" / "skill-creator" / "SKILL.md"
    if not path.is_file():
        return "(skill-creator/SKILL.md not found)"
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        return text[: max_chars - 40] + "\n\n...[skill-creator truncated]...\n"
    return text


def _redact_prediction(data: dict[str, Any]) -> dict[str, Any]:
    """Strip gold / exact answers before sending traj digests to the LLM."""
    out = dict(data)
    out.pop("ground_truth", None)
    out.pop("guidelines", None)
    # Keep conversation; drop prediction if it was forced to GT for scoring.
    out.pop("prediction", None)
    # Truncate conversation steps for prompt budget
    conv = out.get("conversation") or out.get("messages") or []
    if isinstance(conv, list) and len(conv) > 40:
        head, tail = conv[:18], conv[-18:]
        out["conversation"] = head + [{"role": "user", "content": "[...truncated...]"}] + tail
        out.pop("messages", None)
    return out


def _summarize_traj_dir(traj_dir: Path, *, max_success: int, max_fail: int, max_chars: int) -> str:
    blocks: list[str] = []
    query_dirs = sorted(
        [p for p in traj_dir.iterdir() if p.is_dir() and not p.name.startswith("_")],
        key=lambda p: p.name,
    )
    n_success = n_fail = 0
    for qdir in query_dirs:
        for label, bucket, limit in (
            ("SUCCESS", qdir / "success", max_success),
            ("FAIL", qdir / "fail", max_fail),
        ):
            if not bucket.is_dir():
                continue
            files = sorted(bucket.glob("prediction_*.json"))
            for path in files:
                if label == "SUCCESS" and n_success >= limit:
                    continue
                if label == "FAIL" and n_fail >= limit:
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                redacted = _redact_prediction(raw)
                blob = json.dumps(redacted, ensure_ascii=False, indent=2)
                if len(blob) > max_chars:
                    blob = blob[: max_chars - 30] + "\n...[truncated]...\n"
                blocks.append(
                    f"## [{label}] query_id={qdir.name} file={path.name}\n```json\n{blob}\n```\n"
                )
                if label == "SUCCESS":
                    n_success += 1
                else:
                    n_fail += 1
    header = (
        f"# Trajectory digests\n"
        f"Included success={n_success} fail={n_fail} "
        f"(caps success≤{max_success} fail≤{max_fail} per suite).\n\n"
    )
    return header + "\n".join(blocks)


def _chat_complete(*, system: str, user: str, max_tokens: int, temperature: float) -> str:
    load_baseline_env()
    base_url, api_key, model = resolve_openai_compat()
    if not api_key or not model:
        raise SystemExit(
            "Missing OPENAI_COMPATIBLE_API_KEY / OPENAI_COMPATIBLE_MODEL in ~/baseline/.env"
        )
    try:
        from openai import OpenAI
    except ImportError as e:
        raise SystemExit("pip install openai  (required for offline skill author)") from e

    client = OpenAI(api_key=api_key, base_url=base_url or None)
    print(f"[llm] model={model} base={base_url or '(default)'}")
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise SystemExit("Empty LLM response")
    return content


_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$", re.IGNORECASE)


def _extract_skill_md(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    if not text.startswith("---"):
        # Prepend minimal frontmatter if model forgot
        text = (
            "---\n"
            "name: dataclaw-workflows\n"
            "description: AMC-authored workflows for DataClaw analysis tasks.\n"
            "---\n\n" + text
        )
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--traj-dir", type=Path, required=True)
    p.add_argument("--skill-output-dir", type=Path, required=True)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--task-name", default="dataclaw")
    p.add_argument("--max-success", type=int, default=12)
    p.add_argument("--max-fail", type=int, default=8)
    p.add_argument("--max-traj-chars", type=int, default=8000)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--dry-run", action="store_true", help="Build prompt only; no LLM call")
    args = p.parse_args(argv)

    if not args.traj_dir.is_dir():
        print(f"[error] missing traj dir: {args.traj_dir}", file=sys.stderr)
        return 1

    system, create_tpl, verifier_prompt = _load_amc_prompts()
    skill_dir = args.skill_output_dir
    skill_dir.mkdir(parents=True, exist_ok=True)

    objective = create_tpl.format(
        task=args.task_name,
        traj_dir=str(args.traj_dir),
        skill_dir=str(skill_dir),
        data_dir=str(args.data_dir),
        verifier_prompt=verifier_prompt,
    )
    digests = _summarize_traj_dir(
        args.traj_dir,
        max_success=args.max_success,
        max_fail=args.max_fail,
        max_chars=args.max_traj_chars,
    )
    user = "\n\n".join(
        [
            objective,
            OUTPUT_CONTRACT,
            "# skill-creator guidance (inlined)\n" + _skill_creator_digest(),
            digests,
            "Now write the complete SKILL.md contents only.",
        ]
    )

    prompt_path = skill_dir / "author_prompt.txt"
    prompt_path.write_text(
        f"=== SYSTEM ===\n{system}\n\n=== USER ===\n{user}\n",
        encoding="utf-8",
    )
    print(f"[prompt] wrote {prompt_path} ({prompt_path.stat().st_size} bytes)")

    if args.dry_run:
        write_json(
            skill_dir / "author_dry_run.json",
            {"status": "dry_run", "prompt_bytes": prompt_path.stat().st_size},
        )
        print("[dry-run] skipping LLM")
        return 0

    raw = _chat_complete(
        system=system,
        user=user,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    skill_md = _extract_skill_md(raw)
    out = skill_dir / "SKILL.md"
    out.write_text(skill_md, encoding="utf-8")
    write_json(
        skill_dir / "author_meta.json",
        {
            "chars": len(skill_md),
            "traj_dir": str(args.traj_dir),
            "data_dir": str(args.data_dir),
            "mode": "offline_api_author",
        },
    )
    print(f"[ok] wrote {out} ({len(skill_md)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
