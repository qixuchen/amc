#!/usr/bin/env python3
"""Normalize AMC-authored SKILL.md → OpenClaw-injectable export/SKILL.md."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .common import repo_root

REQUIRED_NAME = "dataclaw-workflows"
DEFAULT_DESCRIPTION = (
    "AMC offline skill for DataClaw local CSV / database analysis workflows."
)

_GOLDISH = re.compile(
    r"(?i)\b(ground\s*truth|gold\s*answer|expected\s*answer|qa_gold|milestone\s*expected)\b"
)

# Models sometimes wrap a second frontmatter in a yaml fence right after the real one.
_NESTED_FM_FENCE = re.compile(
    r"^```(?:yaml|yml)?\s*\n(---\s*\n[\s\S]*?\n---\s*)\n```\s*\n*",
    re.IGNORECASE,
)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.strip()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip().strip("'").strip('"')
    return meta, parts[2].lstrip("\n")


def normalize(text: str) -> str:
    meta, body = _split_frontmatter(text)
    body = body.lstrip("\n")

    nested = _NESTED_FM_FENCE.match(body)
    if nested:
        nested_meta, _ = _split_frontmatter(nested.group(1).strip())
        # Prefer the longer / more specific nested description when present.
        nested_desc = (nested_meta.get("description") or "").strip()
        outer_desc = (meta.get("description") or "").strip()
        if nested_desc and (not outer_desc or len(nested_desc) > len(outer_desc)):
            meta["description"] = nested_desc
        if nested_meta.get("name"):
            meta.setdefault("name", nested_meta["name"])
        body = body[nested.end() :]

    name = meta.get("name") or REQUIRED_NAME
    if name != REQUIRED_NAME:
        print(f"[warn] renaming skill name {name!r} → {REQUIRED_NAME!r}", file=sys.stderr)
        name = REQUIRED_NAME
    desc = meta.get("description") or DEFAULT_DESCRIPTION
    hits = _GOLDISH.findall(body)
    if hits:
        print(f"[warn] possible gold-leak keywords: {sorted(set(hits))}", file=sys.stderr)
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--src",
        type=Path,
        default=None,
        help="Source SKILL.md (default: outputs/.../skills/SKILL.md)",
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    root = repo_root()
    src = args.src or (
        root / "outputs" / "dataclaw_learn20" / "skill_manager" / "iter_0" / "skills" / "SKILL.md"
    )
    out = args.out or (root / "export" / "SKILL.md")

    if not src.is_file():
        print(f"[error] missing source skill: {src}", file=sys.stderr)
        return 1

    doc = normalize(src.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"[ok] wrote {out} ({len(doc)} chars) from {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
