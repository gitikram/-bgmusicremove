/** Input controls: file upload (with drag & drop) and media URL submission. */

import { useRef, useState } from 'react'
import { createUploadJob, createUrlJob, type HealthInfo, type Job } from '../api'

interface Props {
  health: HealthInfo | null
  onJobCreated: (job: Job) => void
  onError: (message: string) => void
}

type Tab = 'upload' | 'url'

export default function InputPanel({ health, onJobCreated, onError }: Props) {
  const [tab, setTab] = useState<Tab>('upload')
  const [url, setUrl] = useState('')
  const [dragging, setDragging] = useState(false)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const maxMb = health?.limits.max_upload_mb ?? 300
  const maxMin = Math.round((health?.limits.max_duration_sec ?? 1200) / 60)

  const startUpload = async (file: File) => {
    if (file.size > maxMb * 1024 * 1024) {
      onError(`File is larger than the ${maxMb} MB limit.`)
      return
    }
    setUploadPct(0)
    try {
      const job = await createUploadJob(file, setUploadPct)
      onJobCreated(job)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploadPct(null)
    }
  }

  const submitUrl = async () => {
    if (!url.trim()) return
    try {
      const job = await createUrlJob(url.trim())
      setUrl('')
      onJobCreated(job)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void startUpload(file)
  }

  return (
    <div className="panel">
      {/* Tabs */}
      <div className="mb-5 inline-flex rounded-xl border border-zinc-800 bg-zinc-950 p-1">
        {(
          [
            ['upload', 'Upload file'],
            ['url', 'Video URL'],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${
              tab === key ? 'bg-brand-600 text-white' : 'text-zinc-400 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'upload' ? (
        <div>
          <div
            role="button"
            tabIndex={0}
            aria-label="Upload an audio or video file"
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => e.key === 'Enter' && fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition ${
              dragging ? 'border-brand-500 bg-brand-500/10' : 'border-zinc-700 hover:border-zinc-500'
            }`}
          >
            <svg viewBox="0 0 24 24" className="mb-3 h-10 w-10 text-brand-400" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0L8 8m4-4l4 4" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            <p className="font-medium">Drop an MP3, WAV, or video here</p>
            <p className="mt-1 text-sm text-zinc-400">or click to browse — up to {maxMb} MB / {maxMin} minutes</p>
            <input
              ref={fileInput}
              type="file"
              accept="audio/*,video/*,.mp3,.wav,.m4a,.flac,.mp4,.mov,.webm,.mkv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void startUpload(file)
                e.target.value = ''
              }}
            />
          </div>
          {uploadPct !== null && (
            <div className="mt-4">
              <div className="mb-1 flex justify-between text-xs text-zinc-400">
                <span>Uploading…</span>
                <span>{uploadPct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${uploadPct}%` }} />
              </div>
            </div>
          )}
        </div>
      ) : (
        <div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void submitUrl()}
              placeholder="https://www.youtube.com/watch?v=…"
              className="w-full flex-1 rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-2.5 text-sm outline-none transition placeholder:text-zinc-600 focus:border-brand-500"
            />
            <button type="button" className="btn-primary" onClick={() => void submitUrl()} disabled={!url.trim()}>
              Separate audio
            </button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-zinc-500">
            Audio is fetched from the URL and separated server-side. Downloading media from third-party platforms may
            violate their terms of service — only process content you have the right to use.
          </p>
        </div>
      )}
    </div>
  )
}
