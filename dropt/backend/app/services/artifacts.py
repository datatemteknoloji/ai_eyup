from __future__ import annotations

import os
from pathlib import Path

ARTIFACT_DIR = Path(os.environ.get("PORTAL_ARTIFACT_DIR", "/artifacts"))


def ensure_artifact_dir(*parts: str) -> Path:
    path = ARTIFACT_DIR.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_artifact_dir(job_id: int) -> Path:
    return ensure_artifact_dir(f"job-{job_id}")
