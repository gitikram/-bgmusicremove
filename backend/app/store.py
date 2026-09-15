"""Filesystem-backed job store: one JSON document per job under data/jobs/{id}/job.json.

The store is intentionally simple so the API process and an RQ worker process can
share state without a database. Writes are last-writer-wins; the API and the
worker update disjoint fields at disjoint times, which is sufficient for MVP.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import settings

_LOCK = threading.Lock()

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
TERMINAL = {STATUS_DONE, STATUS_FAILED, STATUS_EXPIRED}


def _jobs_root() -> Path:
    return settings.data_dir / "jobs"


def job_dir(job_id: str) -> Path:
    return _jobs_root() / job_id


def _job_file(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def create_job(source: str, ip: str, display_name: str = "", url: str = "") -> dict[str, Any]:
    job_id = new_job_id()
    now = _now_iso()
    job: dict[str, Any] = {
        "id": job_id,
        "status": STATUS_QUEUED,
        "stage": "queued",
        "progress": 0,
        "error": None,
        "source": source,  # "upload" | "url"
        "source_name": display_name,
        "url": url,
        "is_video": False,
        "duration_sec": None,
        "quota_ip": ip,
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
        "outputs": {},
    }
    job_dir(job_id).mkdir(parents=True, exist_ok=True)
    _write(job)
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    f = _job_file(job_id)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    """Read-modify-write a job document. Returns the updated job or None if unknown."""
    with _LOCK:
        job = get_job(job_id)
        if job is None:
            return None
        job.update(fields)
        job["updated_at"] = _now_iso()
        _write(job)
        return job


def delete_job(job_id: str) -> bool:
    """Remove a job document and all of its files. Returns True if the job existed."""
    d = job_dir(job_id)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def list_jobs() -> list[dict[str, Any]]:
    root = _jobs_root()
    if not root.is_dir():
        return []
    jobs = []
    for f in root.glob("*/job.json"):
        try:
            jobs.append(json.loads(f.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return jobs


def count_jobs_today(ip: str) -> int:
    today = time.strftime("%Y-%m-%d")
    return sum(1 for j in list_jobs() if j.get("quota_ip") == ip and str(j.get("created_at", "")).startswith(today))


def _write(job: dict[str, Any]) -> None:
    f = _job_file(job["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(f)
