# ClearVoice — Remove Background Music, Keep the Vocals

ClearVoice is a web tool that separates vocals from background music. Users upload an MP3,
a video file, or paste a media URL; a GPU server runs **Demucs v4 (`htdemucs_ft`)** and returns
a clean vocal track, plus the removed music as a bonus stem and a vocal-only MP4 for video inputs.

```
Browser (React + wavesurfer A/B player)
   │  upload / URL
   ▼
FastAPI ──► Redis + RQ queue ──► Worker
   │                              │ yt-dlp (URLs) / ffmpeg (decode, normalize, MP3, MP4 remux)
   │                              │ Demucs v4 htdemucs_ft (CUDA or CPU)
   ▼                              ▼
 job store (JSON) ◄──────── vocals.wav / no_vocals.wav / vocals.mp3 / vocal_only.mp4
```

## Repository layout

```
backend/            FastAPI app + worker (Python)
  app/api/routes.py HTTP API (upload, URL, status, SSE, streaming, downloads)
  app/jobs.py       pipeline orchestration (ingest → normalize → separate → encode)
  app/services/     ffmpeg helpers, yt-dlp ingestion, Demucs separation
  app/worker.py     RQ worker entry point
  tests/            unit tests (job store, URL validation)
frontend/           Vite + React + Tailwind + wavesurfer.js
docker-compose.yml  CPU stack; docker-compose.gpu.yml adds the GPU worker
```

## Quickstart (local, no Docker)

Prerequisites: **Python 3.11+**, **Node 20+**, and **ffmpeg** on PATH
(Windows: `winget install Gyan.FFmpeg`).

```powershell
# 1. Backend (from the repo root)
cd backend
python -m pip install -r requirements.txt   # torch CPU wheel is fine for testing
copy ..\.env.example .env                   # optional

# Without Redis configured, jobs run on an in-process thread queue.
python -m uvicorn app.main:app --port 8000
```

The first real separation downloads the Demucs weights (~170 MB, two fine-tuned models from the
Hugging Face Hub `adefossez/HTDemucs-ft`) automatically and caches them in
`~/.cache/huggingface`.

> CPU note: without CUDA, `htdemucs_ft` (a bag of two models) runs roughly 10× slower than
> real time — expect a few minutes for a 4-minute song. That is normal; use the GPU Docker
> stack (or set `DEMUCS_MODEL=htdemucs`, the single-model variant) for faster iteration.

```powershell
# 2. Frontend (second terminal, from the repo root)
cd frontend
npm install
npm run dev        # http://localhost:5173, proxies /api to :8000
```

Open http://localhost:5173. `npm run build` produces `frontend/dist`, which the API
also serves automatically at http://localhost:8000 for single-process deployments.

### Testing without the model

Set `DEV_FAKE_SEPARATION=1` (see `.env.example`) to skip Demucs: jobs run through the
whole pipeline instantly and both "stems" are copies of the input. Useful for UI work.

## Production (Docker)

CPU stack (Redis + API + worker + nginx frontend at http://localhost:8080):

```bash
docker compose up --build
```

GPU stack (NVIDIA drivers + nvidia-container-toolkit required):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

Scale workers with `docker compose up --scale worker=2` (each worker needs GPU memory;
run one worker per GPU).

### GPU sizing notes

- `htdemucs_ft` needs roughly 3–6 GB VRAM with default segments; set `DEMUCS_SEGMENT=8`
  if you hit out-of-memory errors, or raise it (e.g. 20–30) on 16 GB+ cards for speed.
- Expect near-real-time processing on an RTX 3090/4090 class GPU and roughly 10× slower
  than real-time on CPU.
- GPU hosts that work well: RunPod, Vast.ai, Lambda Labs, Fly.io GPU.

## Configuration

All settings live in `.env.example` and are documented inline: upload size, max duration,
per-IP daily quota, model selection, queue backend, file TTL, CORS origins.

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Backend capabilities and limits |
| POST | `/api/jobs/upload` | Multipart upload → creates a job (201) |
| POST | `/api/jobs/url` | `{"url": "..."}` → creates a job (201) |
| GET | `/api/jobs/{id}` | Job status/progress/outputs (also `/events` for SSE) |
| GET | `/api/jobs/{id}/audio/{original\|vocals\|music}` | Stream audio (HTTP Range supported) |
| GET | `/api/jobs/{id}/download/{vocals-mp3\|vocals-wav\|music-mp3\|music-wav\|video}` | Download outputs |
| DELETE | `/api/jobs/{id}` | Delete the job and its files immediately |

Job IDs act as unguessable capability tokens in the MVP; add authentication before
exposing the service publicly.

## Legal notes

- Fetching media via yt-dlp from platforms like YouTube violates their terms of service.
  The UI shows a disclaimer; keep processing transient (files auto-delete after
  `FILE_TTL_HOURS`), never redistribute content, and consider restricting URL mode for
  commercial deployments.
- Demucs is MIT-licensed; model weights are free for commercial use.
- Only process audio you have the rights to use.

## Roadmap

- Phase 3 candidates: Chrome extension accelerator (deep-links into the web app),
  batch processing, MDX-Net ensemble quality tier, user accounts and quotas.
