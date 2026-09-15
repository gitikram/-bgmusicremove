/** App shell: state machine (input -> progress -> results / error), health banner, job history. */

import { useCallback, useEffect, useState } from 'react'
import { getHealth, watchJob, type HealthInfo, type Job } from './api'
import HeroDiagram from './components/HeroDiagram'
import InputPanel from './components/InputPanel'
import ProgressView from './components/ProgressView'
import ResultsView from './components/ResultsView'

const HISTORY_KEY = 'clearvoice.jobs'
const HISTORY_LIMIT = 5

function readHistory(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter((x) => typeof x === 'string').slice(0, HISTORY_LIMIT) : []
  } catch {
    return []
  }
}

function rememberJob(id: string): string[] {
  const next = [id, ...readHistory().filter((x) => x !== id)].slice(0, HISTORY_LIMIT)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  return next
}

function jobIdFromLocation(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('job')
}

function setJobIdInLocation(id: string | null) {
  const url = new URL(window.location.href)
  if (id) url.searchParams.set('job', id)
  else url.searchParams.delete('job')
  window.history.replaceState(null, '', url)
}

export default function App() {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [jobId, setJobId] = useState<string | null>(jobIdFromLocation())
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>(readHistory)

  // Fetch server capabilities for the input hints and the dev-mode banner.
  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  // Watch the active job via SSE (falls back to polling inside watchJob).
  useEffect(() => {
    setJob(null)
    setError(null)
    setJobIdInLocation(jobId)
    if (!jobId) return
    const stop = watchJob(
      jobId,
      (j) => {
        setJob(j)
        if (j.status === 'done') setHistory(rememberJob(j.id))
      },
      (message) => setError(message),
    )
    return stop
  }, [jobId])

  const onJobCreated = useCallback((created: Job) => {
    setHistory(rememberJob(created.id))
    setJobId(created.id)
  }, [])

  const reset = useCallback(() => {
    setJobId(null)
    setJob(null)
    setError(null)
    setJobIdInLocation(null)
  }, [])

  const inProgress = job !== null && (job.status === 'queued' || job.status === 'processing')
  const failed = job?.status === 'failed' || job?.status === 'expired'

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col px-4 pb-10">
      {/* Header */}
      <header className="flex items-center justify-between py-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600">
            <svg viewBox="0 0 32 32" className="h-5 w-5" fill="none">
              <path d="M6 16q2.5-9 5 0t5 0 5 0 5 0" stroke="white" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
          </span>
          <span className="text-lg font-semibold tracking-tight">ClearVoice</span>
        </div>
        {health && (
          <span className="text-xs text-zinc-500">
            {health.model}
            {health.fake_separation ? ' · dev mode' : ''}
          </span>
        )}
      </header>

      {health?.fake_separation && (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-300">
          Server is running in DEV_FAKE_SEPARATION mode — outputs are placeholders, not real AI separation.
        </div>
      )}

      {/* Hero */}
      {jobId === null && (
        <section className="mb-8">
          <h1 className="text-center text-3xl font-bold tracking-tight sm:text-4xl">
            Remove the music.{' '}
            <span className="bg-gradient-to-r from-brand-400 to-brand-600 bg-clip-text text-transparent">
              Keep the voice.
            </span>
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-center text-sm text-zinc-400">
            Upload a song or video (or paste a URL) and the AI isolates the vocals — clean speech or singing with the
            background music stripped away.
          </p>
          <div className="mt-6">
            <HeroDiagram />
          </div>
        </section>
      )}

      {/* Main card */}
      <main className="flex-1">
        {error && (
          <div className="panel border-brand-700/50">
            <h2 className="text-lg font-semibold text-brand-400">Something went wrong</h2>
            <p className="mt-2 text-sm text-zinc-300">{error}</p>
            <button type="button" onClick={reset} className="btn-primary mt-5">
              Start over
            </button>
          </div>
        )}

        {!error && job === null && (
          <InputPanel health={health} onJobCreated={onJobCreated} onError={setError} />
        )}

        {!error && inProgress && job !== null && <ProgressView job={job} />}

        {!error && job?.status === 'done' && <ResultsView job={job} onReset={reset} />}

        {!error && failed && job !== null && (
          <div className="panel border-brand-700/50">
            <h2 className="text-lg font-semibold text-brand-400">
              {job.status === 'expired' ? 'This job has expired' : 'Processing failed'}
            </h2>
            <p className="mt-2 text-sm text-zinc-300">{job.error ?? 'Please try again.'}</p>
            <button type="button" onClick={reset} className="btn-primary mt-5">
              Start over
            </button>
          </div>
        )}

        {/* Recent jobs (kept client-side; server files expire after the TTL) */}
        {jobId === null && history.length > 0 && (
          <section className="mt-6">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">Recent jobs</h3>
            <div className="flex flex-wrap gap-2">
              {history.map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setJobId(id)}
                  className="rounded-lg border border-zinc-800 px-3 py-1.5 font-mono text-xs text-zinc-400 transition hover:border-zinc-600 hover:text-white"
                >
                  {id}
                </button>
              ))}
            </div>
          </section>
        )}
      </main>

      <footer className="mt-12 border-t border-zinc-900 pt-5 text-center text-xs leading-relaxed text-zinc-600">
        Powered by Demucs v4 running on a GPU server · Only process audio you have the rights to use.
      </footer>
    </div>
  )
}
