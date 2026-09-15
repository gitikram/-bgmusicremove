"""ffmpeg / ffprobe helpers: probing, normalization, MP3 encoding, and video remuxing."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

_COPYABLE_AUDIO_EXT = {".wav", ".flac"}  # decodable by soundfile without ffmpeg


class MediaError(RuntimeError):
    """Raised when a media operation fails; message is user-presentable."""


def require_ffmpeg() -> None:
    if not FFMPEG or not FFPROBE:
        raise MediaError(
            "ffmpeg/ffprobe were not found on PATH. "
            "Install ffmpeg (Windows: `winget install Gyan.FFmpeg`) and restart the server."
        )


def probe(path: Path) -> dict:
    """Return {"duration": float | None, "has_video": bool, "has_audio": bool}."""
    require_ffmpeg()
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True).stdout
    except subprocess.SubprocessError as exc:
        raise MediaError(f"Could not read media metadata (is the file a valid audio/video?)") from exc
    info = json.loads(out or "{}")
    streams = info.get("streams", [])
    duration = None
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    return {
        "duration": duration,
        "has_video": any(s.get("codec_type") == "video" for s in streams),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def normalize_to_wav(src: Path, dst: Path) -> Path:
    """Decode any input to 44.1 kHz stereo 16-bit PCM WAV (Demucs' native format)."""
    if not FFMPEG:
        # Graceful dev fallback: soundfile can read plain WAV/FLAC without ffmpeg.
        if src.suffix.lower() in _COPYABLE_AUDIO_EXT:
            shutil.copyfile(src, dst)
            return dst
        raise MediaError("ffmpeg is required to decode this file, but it was not found on PATH.")
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_s16le", str(dst),
    ]
    _run(cmd, "Audio decoding/normalization failed")
    return dst


def encode_mp3(src: Path, dst: Path) -> Path | None:
    """Encode a WAV to MP3 for convenient download. Returns None if lame is unavailable."""
    if not FFMPEG:
        return None
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-codec:a", "libmp3lame", "-q:a", "2", str(dst),
    ]
    try:
        _run(cmd, "MP3 encoding failed")
        return dst
    except MediaError:
        return None  # WAV downloads still work without libmp3lame


def remux_vocal_video(video: Path, vocals_wav: Path, dst: Path) -> Path:
    """Replace the video's audio track with the vocals-only stem.

    Tries a lossless stream copy first and falls back to re-encoding the video
    when the source codec is not MP4-compatible (e.g. VP9/Opus in WebM).
    """
    if not FFMPEG:
        raise MediaError("ffmpeg is required for video output, but it was not found on PATH.")
    copy_cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-i", str(vocals_wav),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(dst),
    ]
    try:
        _run(copy_cmd, "Video remux failed")
        return dst
    except MediaError:
        encode_cmd = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-i", str(vocals_wav),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(dst),
        ]
        _run(encode_cmd, "Video re-encoding failed")
        return dst


def _run(cmd: list[str], error_context: str, timeout: int = 3600) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.SubprocessError as exc:
        raise MediaError(f"{error_context}: {exc}") from exc
    if proc.returncode != 0:
        tail = [line for line in (proc.stderr or "").strip().splitlines() if line.strip()][-3:]
        raise MediaError(f"{error_context}: " + (" | ".join(tail) or f"exit code {proc.returncode}"))
