"""HTTP API: job creation, status (polling + SSE), audio streaming, downloads, cleanup."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, field_validator

from .. import queueing, store
from ..config import settings
from ..services import ingest as ingest_svc
from ..services import media as media_svc

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# job.json is excluded when locating uploads; anything else matching input.* is media
_UPLOAD_SKIP_EXT = {".json", ".tmp"}

_AUDIO_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
}
_VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


# --------------------------------------------------------------------------
# health / limits
# --------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "queue": queueing.queue_backend_name(),
        "model": settings.demucs_model,
        "fake_separation": settings.dev_fake_separation,
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_duration_sec": settings.max_duration_sec,
            "quota_per_ip_per_day": settings.quota_per_ip_per_day,
        },
    }


# --------------------------------------------------------------------------
# job creation
# --------------------------------------------------------------------------

class UrlJobRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("url is required")
        return v


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_quota(ip: str) -> None:
    if settings.quota_per_ip_per_day > 0 and store.count_jobs_today(ip) >= settings.quota_per_ip_per_day:
        raise HTTPException(status_code=429, detail="Daily job quota exceeded. Please try again tomorrow.")


def _safe_suffix(name: str | None) -> str:
    if not name or "." not in name:
        return ".bin"
    suffix = "." + name.rsplit(".", 1)[1].lower()
    return suffix if re.match(r"^\.[a-z0-9]{1,5}$", suffix) else ".bin"


@router.post("/jobs/upload", status_code=201)
async def create_upload_job(request: Request, file: UploadFile = File(...)) -> dict:
    ip = _client_ip(request)
    _check_quota(ip)

    job = store.create_job("upload", ip, display_name=file.filename or "upload")
    jdir = store.job_dir(job["id"])
    dest = jdir / f"input{_safe_suffix(file.filename)}"

    try:
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large; the limit is {settings.max_upload_mb} MB.",
                    )
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty upload.")
    except HTTPException:
        store.delete_job(job["id"])
        raise
    except OSError as exc:
        store.delete_job(job["id"])
        raise HTTPException(status_code=500, detail=f"Could not store the upload: {exc}") from exc
    finally:
        await file.close()

    queueing.enqueue_job(job["id"])
    return _job_payload(store.get_job(job["id"]) or job)


@router.post("/jobs/url", status_code=201)
def create_url_job(request: Request, body: UrlJobRequest) -> dict:
    ip = _client_ip(request)
    _check_quota(ip)
    try:
        ingest_svc.validate_url(body.url)
    except ingest_svc.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = store.create_job("url", ip, url=body.url, display_name=body.url)
    queueing.enqueue_job(job["id"])
    return _job_payload(job)


# --------------------------------------------------------------------------
# status: polling + SSE
# --------------------------------------------------------------------------

@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return _job_payload(job)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events stream of job status updates; closes when the job is terminal."""

    async def gen():
        last_payload: str | None = None
        while True:
            if await request.is_disconnected():
                return
            job = store.get_job(job_id)
            if job is None:
                yield "event: gone\ndata: job not found\n\n"
                return
            payload = json.dumps(_job_payload(job), ensure_ascii=False)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            if job.get("status") in store.TERMINAL:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    if not store.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    return Response(status_code=204)


# --------------------------------------------------------------------------
# media streaming / downloads
# --------------------------------------------------------------------------

@router.get("/jobs/{job_id}/audio/{kind}")
def stream_audio(job_id: str, kind: str, request: Request):
    """Stream original / vocals / music audio with HTTP Range support (browser seeking)."""
    job = _require_job(job_id)
    mapping = {
        "original": ("normalized.wav", None),
        "vocals": (job.get("outputs", {}).get("vocals_wav", "vocals.wav"), None),
        "music": (job.get("outputs", {}).get("music_wav", "no_vocals.wav"), None),
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail="Unknown audio stream.")
    filename, _ = mapping[kind]
    path = store.job_dir(job_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=409, detail="Audio is not ready yet.")
    return _file_response(request, path, _guess_audio_type(path))


@router.get("/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str, request: Request):
    job = _require_job(job_id)
    outputs = job.get("outputs", {})
    mapping = {
        "vocals-wav": (outputs.get("vocals_wav", ""), "vocals"),
        "vocals-mp3": (outputs.get("vocals_mp3", ""), "vocals"),
        "music-wav": (outputs.get("music_wav", ""), "music_removed"),
        "music-mp3": (outputs.get("music_mp3", ""), "music_removed"),
        "video": (outputs.get("video", ""), "vocals_only_video"),
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail="Unknown download.")
    filename, label = mapping[kind]
    if not filename:
        raise HTTPException(status_code=409, detail="That output is not available for this job.")
    path = store.job_dir(job_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=409, detail="Output file is missing.")
    return _file_response(request, path, _guess_audio_type(path) if kind != "video" else "video/mp4", download_name=f"{label}.{path.suffix.lstrip('.')}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _require_job(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job


def _guess_audio_type(path: Path) -> str:
    return _AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _file_response(
    request: Request,
    path: Path,
    media_type: str,
    download_name: str | None = None,
):
    """Streaming file response with Range support so audio seeking works in browsers."""
    size = path.stat().st_size
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'

    status_code = 200
    start, end = 0, size - 1
    range_header = request.headers.get("range")
    if range_header:
        match = _RANGE_RE.match(range_header.strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
            else:  # suffix range: last N bytes
                start = max(0, size - int(match.group(2)))
            if start >= size or start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{size}"},
                )
            end = min(end, size - 1)
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    length = end - start + 1

    def iter_file():
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(iter_file(), status_code=status_code, media_type=media_type, headers=headers)


def _job_payload(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if job is None:
        return None
    payload = dict(job)
    base = f"/api/jobs/{job['id']}"
    payload["audio"] = {k: f"{base}/audio/{k}" for k in ("original", "vocals", "music")}
    outs = job.get("outputs") or {}
    downloads: dict[str, str] = {}
    if outs.get("vocals_wav"):
        downloads["vocals_wav"] = f"{base}/download/vocals-wav"
    if outs.get("vocals_mp3"):
        downloads["vocals_mp3"] = f"{base}/download/vocals-mp3"
    if outs.get("music_wav"):
        downloads["music_wav"] = f"{base}/download/music-wav"
    if outs.get("music_mp3"):
        downloads["music_mp3"] = f"{base}/download/music-mp3"
    if outs.get("video"):
        downloads["video"] = f"{base}/download/video"
    payload["downloads"] = downloads
    return payload


# --------------------------------------------------------------------------
# retention
# --------------------------------------------------------------------------

def run_cleanup_once() -> int:
    """Delete terminal jobs older than the TTL. Returns the number removed."""
    ttl_sec = settings.file_ttl_hours * 3600
    now = time.time()
    removed = 0
    for job in store.list_jobs():
        if job.get("status") not in store.TERMINAL:
            continue
        try:
            updated = time.mktime(time.strptime(job.get("updated_at", ""), "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            continue
        if now - updated >= ttl_sec:
            if store.delete_job(job["id"]):
                removed += 1
    if removed:
        log.info("cleanup removed %d expired job(s)", removed)
    return removed


async def cleanup_loop() -> None:
    interval = max(60, settings.cleanup_interval_min * 60)
    while True:
        await asyncio.sleep(interval)
        try:
            run_cleanup_once()
        except Exception:  # noqa: BLE001 - cleanup must never take the API down
            log.exception("cleanup pass failed")
