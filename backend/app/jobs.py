"""Job orchestration: the ingest -> normalize -> separate -> encode -> deliver pipeline.

run_job(job_id) is the single entry point invoked by both queue backends
(in-process thread pool and the RQ worker process).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from . import store
from .config import settings
from .services import ingest, media, separation

log = logging.getLogger(__name__)


def run_job(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None or job.get("status") in store.TERMINAL:
        return
    try:
        _run_pipeline(job_id, job)
    except Exception as exc:  # noqa: BLE001 - any failure must land in the job record
        log.exception("job %s failed", job_id)
        store.update_job(job_id, status=store.STATUS_FAILED, error=str(exc)[:500], progress=100)


def _run_pipeline(job_id: str, job: dict) -> None:
    jdir = store.job_dir(job_id)

    # ---- 1. ingest ---------------------------------------------------------
    store.update_job(job_id, status=store.STATUS_PROCESSING, stage="ingest", progress=2, error=None)
    if job.get("source") == "url":
        input_path, title = ingest.download_audio(job["url"], jdir, settings.max_duration_sec)
        store.update_job(job_id, source_name=title)
    else:
        input_path = _find_input(jdir)
    store.update_job(job_id, progress=15)

    # ---- 2. probe + normalize ----------------------------------------------
    store.update_job(job_id, stage="normalize", progress=18)
    info = media.probe(input_path)
    if not info["has_audio"]:
        raise media.MediaError("No audio stream was found in the input file.")
    duration = info["duration"]
    if duration and duration > settings.max_duration_sec:
        raise media.MediaError(
            f"Media is about {int(duration // 60)} min long; the limit is {settings.max_duration_sec // 60} min."
        )
    is_video = bool(info["has_video"])
    store.update_job(job_id, is_video=is_video, duration_sec=duration)

    normalized = jdir / "normalized.wav"
    media.normalize_to_wav(input_path, normalized)
    store.update_job(job_id, progress=25)

    # ---- 3. separation ------------------------------------------------------
    store.update_job(job_id, stage="separate", progress=26)
    _start_progress_estimator(job_id, duration or 300.0)
    stems = separation.separate(normalized, jdir)
    store.update_job(job_id, stage="encode", progress=85)

    # ---- 4. encode outputs --------------------------------------------------
    outputs: dict[str, str] = {
        "vocals_wav": stems["vocals"].name,
        "music_wav": stems["music"].name,
    }
    vocals_mp3 = media.encode_mp3(stems["vocals"], jdir / "vocals.mp3")
    if vocals_mp3:
        outputs["vocals_mp3"] = vocals_mp3.name
    music_mp3 = media.encode_mp3(stems["music"], jdir / "no_vocals.mp3")
    if music_mp3:
        outputs["music_mp3"] = music_mp3.name

    if is_video:
        try:
            media.remux_vocal_video(input_path, stems["vocals"], jdir / "vocal_only.mp4")
            outputs["video"] = "vocal_only.mp4"
        except media.MediaError as exc:
            # Audio stems are still valid; the video remix is a bonus deliverable.
            log.warning("job %s: video remux failed (%s)", job_id, exc)

    # ---- 5. done ------------------------------------------------------------
    expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + settings.file_ttl_hours * 3600)
    )
    store.update_job(
        job_id,
        status=store.STATUS_DONE,
        stage="done",
        progress=100,
        outputs=outputs,
        expires_at=expires_at,
    )
    log.info("job %s done: %s", job_id, ", ".join(outputs.values()))


def _find_input(jdir: Path) -> Path:
    skip_ext = {".json", ".tmp"}
    candidates = [p for p in sorted(jdir.glob("input.*")) if p.suffix.lower() not in skip_ext]
    if not candidates:
        raise RuntimeError("Uploaded file is missing from the job directory.")
    return candidates[0]


def _start_progress_estimator(job_id: str, duration_sec: float) -> None:
    """apply_model() offers no progress callback, so estimate from elapsed time.

    The loop self-terminates as soon as the job leaves the 'separate' stage.
    Speed factors are rough: htdemucs_ft runs near real-time on a modern GPU
    and roughly 8-15x slower than real-time on CPU.
    """
    device = separation.resolve_device()
    expected = max(5.0, duration_sec * (0.9 if device == "cuda" else 12.0))
    t0 = time.monotonic()

    def loop() -> None:
        while True:
            time.sleep(2.0)
            job = store.get_job(job_id)
            if not job or job.get("stage") != "separate" or job.get("status") != store.STATUS_PROCESSING:
                return
            pct = min(84, 26 + int(58 * (time.monotonic() - t0) / expected))
            if pct > job.get("progress", 0):
                store.update_job(job_id, progress=pct)

    threading.Thread(target=loop, daemon=True, name=f"progress-{job_id}").start()
