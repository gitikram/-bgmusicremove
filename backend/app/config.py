"""Application configuration, loaded from environment variables and an optional .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- storage ---
    data_dir: Path = BASE_DIR / "data"

    # --- limits / guardrails ---
    max_upload_mb: int = 300
    max_duration_sec: int = 1200  # 20 minutes per job
    quota_per_ip_per_day: int = 20

    # --- separation model ---
    demucs_model: str = "htdemucs_ft"
    demucs_segment: int | None = None  # None = model default (~7.8 s chunks)
    demucs_overlap: float = 0.25
    device: str = "auto"  # auto | cuda | cpu

    # --- queue ---
    redis_url: str | None = None  # e.g. redis://localhost:6379/0 ; unset = in-process thread queue
    max_concurrent_jobs: int = 1

    # --- retention ---
    file_ttl_hours: int = 24
    cleanup_interval_min: int = 30

    # --- dev ---
    dev_fake_separation: bool = False  # skip Demucs; copies input to both stems (pipeline testing only)

    # --- CORS ---
    allowed_origins: str = "http://localhost:5173,http://localhost:4173,http://localhost:8080"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        (self.data_dir / "jobs").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
