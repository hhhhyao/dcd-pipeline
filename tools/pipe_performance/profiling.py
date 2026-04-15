"""Small profiling primitives reusable across local pipe optimization work."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class TimingProfile:
    """Collect stage and hotspot timings for one run."""

    run_name: str
    metadata: dict[str, object] = field(default_factory=dict)
    stages: dict[str, float] = field(default_factory=dict)
    hotspots: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int | float] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def add_stage(self, name: str, seconds: float) -> None:
        self.stages[name] = self.stages.get(name, 0.0) + float(seconds)

    def add_hotspot(self, name: str, seconds: float) -> None:
        self.hotspots[name] = self.hotspots.get(name, 0.0) + float(seconds)

    def add_counter(self, name: str, value: int | float) -> None:
        self.counters[name] = value

    @property
    def total_seconds(self) -> float:
        if "total" in self.stages:
            return self.stages["total"]
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at

    def finish(self) -> None:
        self.finished_at = time.time()
        self.stages.setdefault("total", self.total_seconds)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_name": self.run_name,
            "metadata": self.metadata,
            "stages": self.stages,
            "hotspots": self.hotspots,
            "counters": self.counters,
            "total_seconds": self.total_seconds,
        }

    def write_json(self, path: Path) -> None:
        if self.finished_at is None:
            self.finish()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def time_block(profile: TimingProfile, name: str, *, kind: str = "stage") -> Iterator[None]:
    """Record elapsed seconds into ``profile`` as a stage or hotspot."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if kind == "hotspot":
            profile.add_hotspot(name, elapsed)
        else:
            profile.add_stage(name, elapsed)
