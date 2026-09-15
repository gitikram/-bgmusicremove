"""AI vocal separation built on Demucs v4 (htdemucs_ft).

Heavy imports (torch, demucs) are deferred into functions so the API server can
start and serve health/status endpoints even on machines without the model
installed. A DEV_FAKE_SEPARATION mode copies the input to both stems so the
whole pipeline and UI can be exercised without downloading model weights.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

_model = None
_model_name: str | None = None
_model_device: str | None = None
_model_lock = threading.Lock()


class SeparationError(RuntimeError):
    """Raised for user-facing separation failures."""


def resolve_device() -> str:
    """Effective torch device: explicit setting, else CUDA when available."""
    if settings.device in ("cuda", "cpu"):
        return settings.device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # pragma: no cover - torch missing entirely
        return "cpu"


def _get_model(name: str, device: str):
    global _model, _model_name, _model_device
    with _model_lock:
        if _model is None or _model_name != name or _model_device != device:
            import torch
            from demucs.pretrained import get_model

            log.info("Loading Demucs model '%s' on %s (weights auto-download on first use)", name, device)
            try:
                model = get_model(name)
            except Exception as exc:
                raise SeparationError(
                    f"Could not load model '{name}': {exc}. "
                    "On first run the weights (~170 MB) are downloaded from the Hugging Face Hub "
                    "(adefossez/HTDemucs-ft) - check network access or pre-download them."
                ) from exc
            model.to(device)
            model.eval()
            _model, _model_name, _model_device = model, name, device
        return _model


def separate(wav_path: Path, out_dir: Path) -> dict[str, Path]:
    """Split a normalized WAV into vocals + accompaniment.

    Returns {"vocals": vocals.wav, "music": no_vocals.wav} paths inside out_dir.
    """
    if settings.dev_fake_separation:
        return _fake_separate(wav_path, out_dir)

    import soundfile as sf
    import torch

    from demucs.apply import apply_model

    device = resolve_device()
    model = _get_model(settings.demucs_model, device)

    try:
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    except Exception as exc:
        raise SeparationError(f"Could not read normalized audio: {exc}") from exc
    wav = torch.from_numpy(data.T)  # (channels, samples)

    if sr != model.samplerate:
        import torchaudio.functional as AF

        wav = AF.resample(wav, sr, model.samplerate)
    if wav.shape[0] == 1:  # force stereo like the Demucs CLI does
        wav = wav.repeat(2, 1)

    # Match the normalization used by demucs.separate to avoid clipping drift.
    ref = wav.mean(0)
    std = ref.std() + 1e-8
    wav = (wav - ref.mean()) / std

    log.info("Separating %.1f s of audio on %s (model=%s)", wav.shape[1] / model.samplerate, device, settings.demucs_model)
    with torch.no_grad():
        try:
            sources = apply_model(
                model,
                wav[None],
                device=device,
                split=True,
                overlap=settings.demucs_overlap,
                segment=settings.demucs_segment,
                progress=False,
            )[0]  # -> (sources, channels, samples)
        except torch.cuda.OutOfMemoryError as exc:
            raise SeparationError(
                "GPU ran out of memory. Lower DEMUCS_SEGMENT (e.g. 8) in the environment and retry."
            ) from exc
        except Exception as exc:
            raise SeparationError(f"Separation failed: {exc}") from exc

    sources = sources * std + ref.mean()
    vocals_idx = model.sources.index("vocals")
    other_idx = [i for i, name in enumerate(model.sources) if name != "vocals"]

    out_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = out_dir / "vocals.wav"
    music_path = out_dir / "no_vocals.wav"
    sf.write(str(vocals_path), sources[vocals_idx].t().cpu().numpy(), model.samplerate, subtype="PCM_16")
    sf.write(str(music_path), sources[other_idx].sum(0).t().cpu().numpy(), model.samplerate, subtype="PCM_16")
    log.info("Separation done: %s, %s", vocals_path.name, music_path.name)
    return {"vocals": vocals_path, "music": music_path}


def _fake_separate(wav_path: Path, out_dir: Path) -> dict[str, Path]:
    """Dev mode: no AI. Copies the input to both stems so the UI pipeline is testable."""
    log.warning("DEV_FAKE_SEPARATION is enabled - output stems are placeholders, not real separation.")
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals = out_dir / "vocals.wav"
    music = out_dir / "no_vocals.wav"
    shutil.copyfile(wav_path, vocals)
    shutil.copyfile(wav_path, music)
    return {"vocals": vocals, "music": music}
