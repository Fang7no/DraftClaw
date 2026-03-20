from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def create_run_id(run_name: str | None = None) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid4().hex[:8]
    if run_name:
        safe = "".join(ch for ch in run_name if ch.isalnum() or ch in ("-", "_"))[:32]
        return f"run_{ts}_{safe}_{short}"
    return f"run_{ts}_{short}"


@dataclass
class RunPaths:
    root: Path
    meta: Path
    input: Path
    preprocess: Path
    chunks: Path
    prompts: Path
    responses_raw: Path
    responses_parsed: Path
    state: Path
    final: Path
    logs: Path


class TraceLayout:
    def __init__(self, runs_root: str | Path) -> None:
        self.runs_root = Path(runs_root)

    def create(self, run_id: str) -> RunPaths:
        day_dir = datetime.now().strftime("%Y%m%d")
        root = self.runs_root / day_dir / run_id
        paths = RunPaths(
            root=root,
            meta=root / "meta",
            input=root / "input",
            preprocess=root / "preprocess",
            chunks=root / "chunks",
            prompts=root / "prompts",
            responses_raw=root / "responses" / "raw",
            responses_parsed=root / "responses" / "parsed",
            state=root / "state",
            final=root / "final",
            logs=root / "logs",
        )
        for path in (
            paths.root,
            paths.meta,
            paths.input,
            paths.preprocess,
            paths.chunks,
            paths.prompts,
            paths.responses_raw,
            paths.responses_parsed,
            paths.state,
            paths.final,
            paths.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return paths

