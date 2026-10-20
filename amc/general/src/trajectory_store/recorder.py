"""Record trajectories as LocalFS bundles with idempotent re-recording and an audit log."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .audit import JsonlAuditLogger
from .commit.idempotency import commit_idempotency_key
from .commit.service import CommitCommand, CommitService, _normalize_steps
from .commit.validator import validate_raw_steps
from .repo import LocalFSTrajectoryRepository

AUDIT_FILENAME = "_audit.jsonl"


@dataclass
class RecordResult:
    trajectory_id: str
    status: str
    base_path: Path
    nodes: int
    edges: int
    warnings: list[str] = field(default_factory=list)


class TrajectoryRecorder:
    def __init__(
        self,
        root: str | Path,
        *,
        account_id: str,
        agent_id: str,
        scope: str = "agent",
        idempotency: bool = True,
        max_action_result_chars: int = 12000,
        temporal_fallback_edge: bool = True,
        reasoning_min_confidence: float = 0.55,
        dataflow_extractor: Callable[..., Any] | None = None,
        llm_summarizer: Callable[[list[dict[str, Any]]], tuple[str, str]] | None = None,
    ) -> None:
        self.root = Path(root)
        self.account_id = account_id
        self.agent_id = agent_id
        self.scope = scope
        self.idempotency = idempotency
        self.max_action_result_chars = max_action_result_chars
        self.repo = LocalFSTrajectoryRepository(root=str(self.root))
        self.audit = JsonlAuditLogger(file_path=str(self.root / AUDIT_FILENAME))
        self.service = CommitService(
            max_action_result_chars=max_action_result_chars,
            temporal_fallback_edge=temporal_fallback_edge,
            dataflow_extractor=dataflow_extractor,
            llm_summarizer=llm_summarizer,
            reasoning_min_confidence=reasoning_min_confidence,
        )

    def record(
        self,
        *,
        steps: list[dict[str, Any]],
        session_id: str,
        task_id: str,
        labels: dict[str, Any],
        owner_space: str | None = None,
        trajectory_id: str | None = None,
        force: bool = False,
    ) -> RecordResult:
        command = CommitCommand(
            agent_id=self.agent_id,
            account_id=self.account_id,
            session_id=session_id,
            task_id=task_id,
            trajectory=steps,
            labels=labels,
            trajectory_id=trajectory_id,
            scope=self.scope,
            owner_space=owner_space,
        )
        details = {
            "agent_id": self.agent_id,
            "account_id": self.account_id,
            "scope": command.resolved_scope(),
            "owner_space": command.resolved_owner_space(),
            "session_id": session_id,
            "task_id": task_id,
        }
        check_duplicate = self.idempotency and not force
        try:
            validate_raw_steps(steps)
            if check_duplicate:
                normalized, _ = _normalize_steps(steps, max_chars=self.max_action_result_chars)
                key = commit_idempotency_key(command.resolved_account_id(), task_id, normalized)
                existing = self._load_existing(key)
                if existing is not None:
                    self.audit.write("commit", "idempotent", {**details, "trajectory_id": existing.trajectory_id})
                    return existing
            result = self.service.run(command)
        except Exception as exc:
            self.audit.write("commit", "rejected", {**details, "error": f"{type(exc).__name__}: {exc}"})
            raise

        base_path = self.repo.save_bundle(
            agent_id=self.agent_id,
            account_id=self.account_id,
            scope=command.resolved_scope(),
            owner_space=command.resolved_owner_space(),
            trajectory_id=result.trajectory_id,
            idempotency_key=result.idempotency_key,
            payload=result.payload,
        )
        self.audit.write(
            "commit",
            "accepted" if check_duplicate else "accepted_idempotency_disabled",
            {
                **details,
                "trajectory_id": result.trajectory_id,
                "nodes": result.nodes,
                "edges": result.edges,
                "idempotency_enabled": check_duplicate,
            },
        )
        return RecordResult(
            trajectory_id=result.trajectory_id,
            status="accepted",
            base_path=Path(base_path),
            nodes=result.nodes,
            edges=result.edges,
            warnings=list(result.warnings),
        )

    def _load_existing(self, idempotency_key: str) -> RecordResult | None:
        existing_id = self.repo.find_trajectory_id_by_idempotency_key(idempotency_key)
        if not existing_id:
            return None
        bundle = self.repo.load_trajectory(existing_id)
        if bundle is None:
            return None
        meta = bundle["meta"]
        return RecordResult(
            trajectory_id=existing_id,
            status="idempotent",
            base_path=Path(bundle["base_path"]),
            nodes=int(meta.get("nodes", 0)),
            edges=int(meta.get("edges", 0)),
            warnings=["duplicate commit skipped via idempotency key"],
        )
