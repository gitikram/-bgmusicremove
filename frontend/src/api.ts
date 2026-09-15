/** Typed API client for the ClearVoice backend. */

export type JobStatus = 'queued' | 'processing' | 'done' | 'failed' | 'expired'
export type AudioKind = 'original' | 'vocals' | 'music'

export interface HealthInfo {
  status: string
  queue: 'redis' | 'thread'
  model: string
  fake_separation: boolean
  limits: {
    max_upload_mb: number
    max_duration_sec: number
    quota_per_ip_per_day: number
  }
}

export interface Job {
  id: string
  status: JobStatus
  stage: string
  progress: number
  error: string | null
  source: 'upload' | 'url'
  source_name: string
  url: string
  is_video: boolean
  duration_sec: number | null
  created_at: string
  expires_at: string | null
  audio: Record<AudioKind, string>
  downloads: Record<string, string>
}

const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    if (body && typeof body.detail === 'string') return body.detail
  } catch {
    /* ignore body parse errors */
  }
  return fallback
}

export async function getHealth(): Promise<HealthInfo> {
  const res = await fetch(apiUrl('/api/health'))
  if (!res.ok) throw new Error(`Backend unavailable (HTTP ${res.status})`)
  return res.json()
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(apiUrl(`/api/jobs/${id}`))
  if (!res.ok) throw new Error(await detail(res, `Could not load job (HTTP ${res.status})`))
  return res.json()
}

export function createUrlJob(url: string): Promise<Job> {
  return fetch(apiUrl('/api/jobs/url'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  }).then(async (res) => {
    if (!res.ok) throw new Error(await detail(res, `URL job failed (HTTP ${res.status})`))
    return res.json()
  })
}

export function createUploadJob(file: File, onProgress?: (pct: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    form.append('file', file)
    xhr.open('POST', apiUrl('/api/jobs/upload'))
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status === 201) {
        try {
          resolve(JSON.parse(xhr.responseText) as Job)
        } catch {
          reject(new Error('Malformed server response'))
        }
      } else {
        try {
          const body = JSON.parse(xhr.responseText)
          reject(new Error(typeof body.detail === 'string' ? body.detail : `Upload failed (HTTP ${xhr.status})`))
        } catch {
          reject(new Error(`Upload failed (HTTP ${xhr.status})`))
        }
      }
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.send(form)
  })
}

export async function deleteJob(id: string): Promise<void> {
  await fetch(apiUrl(`/api/jobs/${id}`), { method: 'DELETE' })
}

/** Subscribe to job updates via SSE, falling back to polling when SSE misbehaves. */
export function watchJob(
  id: string,
  onUpdate: (job: Job) => void,
  onError: (message: string) => void,
): () => void {
  let cancelled = false
  let poller: number | undefined
  let es: EventSource | undefined
  let sseFailures = 0

  const stopAll = () => {
    es?.close()
    es = undefined
    if (poller !== undefined) {
      window.clearInterval(poller)
      poller = undefined
    }
  }

  const isTerminal = (job: Job) => job.status === 'done' || job.status === 'failed' || job.status === 'expired'

  const startPolling = () => {
    if (poller !== undefined || cancelled) return
    poller = window.setInterval(async () => {
      try {
        const job = await getJob(id)
        if (cancelled) return
        onUpdate(job)
        if (isTerminal(job)) stopAll()
      } catch (e) {
        if (!cancelled) onError(e instanceof Error ? e.message : String(e))
      }
    }, 1500)
  }

  // Initial fetch so the UI has data even if SSE never connects.
  getJob(id)
    .then((job) => {
      if (!cancelled) onUpdate(job)
    })
    .catch((e) => {
      if (!cancelled) onError(e instanceof Error ? e.message : String(e))
    })

  try {
    es = new EventSource(apiUrl(`/api/jobs/${id}/events`))
    es.onmessage = (ev) => {
      try {
        const job = JSON.parse(ev.data) as Job
        if (cancelled) return
        onUpdate(job)
        if (isTerminal(job)) stopAll()
      } catch {
        /* skip malformed frames */
      }
    }
    es.onerror = () => {
      if (cancelled) return
      sseFailures += 1
      if (sseFailures >= 3) {
        // Server unreachable or SSE blocked - degrade to polling.
        es?.close()
        es = undefined
        startPolling()
      }
    }
  } catch {
    startPolling()
  }

  return () => {
    cancelled = true
    stopAll()
  }
}
