"""Record agent trajectories as LocalFS bundles (steps, raw/clean graphs, L0/L1 summaries)."""

from .recorder import RecordResult, TrajectoryRecorder

__all__ = ["RecordResult", "TrajectoryRecorder"]
