"""run_phase_a.sh orchestration, checked with a stub `python` that only logs its argv."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.unit

SCRIPT = REPO_ROOT / "dataclaw_bridge" / "run_phase_a.sh"
SEP = "\x1f"

STUB = f"""#!/usr/bin/env bash
(IFS='{SEP}'; printf '%s\\n' "$*") >> "$CALL_LOG"
if [[ -n "${{STUB_FAIL:-}}" && "$*" == *"$STUB_FAIL"* ]]; then exit 1; fi
exit 0
"""

PIP = ["-m", "pip", "install", "-q", "openai>=1.0"]


def _phase_a_calls(*, name_substr: str = "20260810", dry_run: bool) -> list[list[str]]:
    pred = str(REPO_ROOT / "cache/dataclaw_learn20/da_agent/iter0_sample0")
    verify = str(REPO_ROOT / "outputs/dataclaw_learn20/verifier/iter_0")
    skills = str(REPO_ROOT / "outputs/dataclaw_learn20/skill_manager/iter_0/skills")
    author = [
        "-m", "dataclaw_bridge.run_offline_skill_author",
        "--traj-dir", verify,
        "--skill-output-dir", skills,
        "--data-dir", "/home/qchenax/DataClaw/assets/database",
    ]
    calls = [
        PIP,
        ["-m", "dataclaw_bridge.convert_predictions", "--name-substr", name_substr,
         "--skill-mode", "baseline", "--output-dir", pred],
        ["-m", "dataclaw_bridge.run_verify", "--predictions-dir", pred, "--workspace", verify],
        author + (["--dry-run"] if dry_run else []),
    ]
    if not dry_run:
        calls.append(
            ["-m", "dataclaw_bridge.export_openclaw_skill", "--src", f"{skills}/SKILL.md",
             "--out", str(REPO_ROOT / "export/SKILL.md")]
        )
    return calls


def _record_call(*, name_substr: str = "20260810", store: str | None = None) -> list[str]:
    return [
        "-m", "dataclaw_bridge.record_trajectories",
        "--name-substr", name_substr,
        "--skill-mode", "baseline",
        "--store-root", store or str(REPO_ROOT / "outputs/trajectory_store"),
    ]


@pytest.fixture
def run_script(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "calls.log"

    def _run(**env_overrides: str) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
        env = {k: v for k, v in os.environ.items()
               if k not in {"RECORD_TRAJ", "TRAJ_STORE", "NAME_SUBSTR", "DRY_RUN", "USE_SUPERVISED", "DATA_DIR"}}
        env.update(PATH=f"{bin_dir}{os.pathsep}{env['PATH']}", CALL_LOG=str(log), **env_overrides)
        log.write_text("", encoding="utf-8")
        proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
        calls = [line.split(SEP) for line in log.read_text(encoding="utf-8").splitlines()]
        return proc, calls

    return _run


def test_default_dry_run_is_unchanged(run_script) -> None:
    proc, calls = run_script(DRY_RUN="1")
    assert proc.returncode == 0, proc.stderr
    assert calls == _phase_a_calls(dry_run=True)


def test_default_full_run_is_unchanged(run_script) -> None:
    proc, calls = run_script()
    assert proc.returncode == 0, proc.stderr
    assert calls == _phase_a_calls(dry_run=False)
    assert "record_trajectories" not in proc.stdout


def test_record_traj_runs_right_after_convert(run_script) -> None:
    proc, calls = run_script(DRY_RUN="1", RECORD_TRAJ="1")
    assert proc.returncode == 0, proc.stderr
    expected = _phase_a_calls(dry_run=True)
    expected.insert(2, _record_call())
    assert calls == expected


def test_record_traj_follows_name_substr_and_store_override(run_script, tmp_path: Path) -> None:
    store = str(tmp_path / "store")
    proc, calls = run_script(DRY_RUN="1", RECORD_TRAJ="1", NAME_SUBSTR="20260811", TRAJ_STORE=store)
    assert proc.returncode == 0, proc.stderr
    expected = _phase_a_calls(name_substr="20260811", dry_run=True)
    expected.insert(2, _record_call(name_substr="20260811", store=store))
    assert calls == expected


def test_record_failure_does_not_stop_phase_a(run_script) -> None:
    proc, calls = run_script(DRY_RUN="1", RECORD_TRAJ="1", STUB_FAIL="dataclaw_bridge.record_trajectories")
    assert proc.returncode == 0, proc.stderr
    assert calls[3:] == _phase_a_calls(dry_run=True)[2:]
    assert "record_trajectories failed" in proc.stdout + proc.stderr


def test_other_step_failures_still_abort(run_script) -> None:
    proc, calls = run_script(DRY_RUN="1", RECORD_TRAJ="1", STUB_FAIL="dataclaw_bridge.convert_predictions")
    assert proc.returncode != 0
    assert calls == _phase_a_calls(dry_run=True)[:2]


def test_script_diff_against_head_only_adds_lines() -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    rel = SCRIPT.relative_to(REPO_ROOT)
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"], capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("run_phase_a.sh not in git HEAD")
    original = head.stdout.splitlines()
    current = SCRIPT.read_text(encoding="utf-8").splitlines()
    it = iter(current)
    missing = [line for line in original if not any(line == c for c in it)]
    assert not missing, f"original lines removed or reordered: {missing}"
