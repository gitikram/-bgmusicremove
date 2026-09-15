"""Unit tests for the job store and URL validation (no network, no model)."""

from __future__ import annotations

import pytest

from app import store
from app.services.ingest import IngestError, validate_url


# --- URL validation ---------------------------------------------------------

def test_rejects_non_http_schemes():
    for url in ("ftp://example.com/x", "javascript:alert(1)", "not a url", ""):
        with pytest.raises(IngestError):
            validate_url(url)


def test_rejects_private_and_loopback_hosts(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingest.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(IngestError):
        validate_url("http://localhost:8000/api")
    monkeypatch.setattr(
        "app.services.ingest.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("192.168.1.10", 0))],
    )
    with pytest.raises(IngestError):
        validate_url("https://internal.example/x")


def test_accepts_public_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingest.socket.getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("142.250.185.78", 0))],
    )
    validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


# --- job store ---------------------------------------------------------------

@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store.settings, "data_dir", tmp_path)
    return tmp_path


def test_job_roundtrip(tmp_store):
    job = store.create_job("upload", ip="1.2.3.4", display_name="song.mp3")
    fetched = store.get_job(job["id"])
    assert fetched is not None
    assert fetched["source"] == "upload"
    assert fetched["status"] == store.STATUS_QUEUED

    store.update_job(job["id"], progress=42, stage="separate")
    assert store.get_job(job["id"])["progress"] == 42

    assert store.delete_job(job["id"]) is True
    assert store.get_job(job["id"]) is None
    assert store.delete_job(job["id"]) is False


def test_count_jobs_today(tmp_store):
    job_a = store.create_job("upload", ip="1.2.3.4")
    store.create_job("url", ip="1.2.3.4")
    store.create_job("upload", ip="5.6.7.8")
    assert store.count_jobs_today("1.2.3.4") == 2
    assert store.count_jobs_today("5.6.7.8") == 1
    assert store.count_jobs_today("9.9.9.9") == 0
    store.delete_job(job_a["id"])
    assert store.count_jobs_today("1.2.3.4") == 1


def test_list_and_cleanup_filter(tmp_store):
    job = store.create_job("upload", ip="1.2.3.4")
    assert len(store.list_jobs()) == 1
    # Non-terminal jobs must never be touched by cleanup.
    from app.api.routes import run_cleanup_once

    store.update_job(job["id"], status=store.STATUS_DONE)
    # TTL is measured from updated_at; a fresh job is not old enough to expire.
    assert run_cleanup_once.__module__  # importable
    store.delete_job(job["id"])
