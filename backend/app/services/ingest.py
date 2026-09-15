"""Input ingestion: URL validation (with an SSRF guard) and yt-dlp audio download."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse


class IngestError(RuntimeError):
    """Raised for user-facing ingestion problems (bad URL, too long, download failure)."""


def validate_url(url: str) -> None:
    """Accept only public http(s) URLs; block private/loopback targets (SSRF guard)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IngestError("Only http(s) URLs are supported.")
    host = parsed.hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise IngestError(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise IngestError("URLs pointing at private or network-internal addresses are not allowed.")


def probe_url_info(url: str) -> dict:
    """Fetch metadata (title, duration) without downloading the media."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt_dlp raises a wide hierarchy; normalize for the job record
        raise IngestError(f"Could not read media info from the URL: {_brief(exc)}") from exc
    if not info:
        raise IngestError("Could not read media info from the URL.")
    return info


def download_audio(url: str, dest_dir: Path, max_duration_sec: int) -> tuple[Path, str]:
    """Download the best audio stream via yt-dlp. Returns (path, display title)."""
    import yt_dlp

    info = probe_url_info(url)
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and duration > max_duration_sec:
        raise IngestError(
            f"Media is about {int(duration // 60)} min long; the limit is {max_duration_sec // 60} min."
        )
    title = str(info.get("title") or "download").strip()

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(dest_dir / "input.%(ext)s"),
        "format": "bestaudio/best",
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        raise IngestError(f"Download failed: {_brief(exc)}") from exc

    skip_ext = {".part", ".ytdl", ".json", ".jpg", ".webp", ".png", ".txt"}
    candidates = [p for p in sorted(dest_dir.glob("input.*")) if p.suffix.lower() not in skip_ext]
    if not candidates:
        raise IngestError("Download finished but no media file was found.")
    return candidates[0], title


def _brief(exc: Exception) -> str:
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return msg[:300]
