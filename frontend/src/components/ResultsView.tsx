/** Results: A/B waveform player plus download actions for every produced output. */

import { deleteJob, apiUrl, type Job } from '../api'
import WaveformAB from './WaveformAB'

interface Props {
  job: Job
  onReset: () => void
}

function formatDuration(sec: number | null): string {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return ` · ${m}:${String(s).padStart(2, '0')}`
}

export default function ResultsView({ job, onReset }: Props) {
  const downloads: { key: string; label: string; primary?: boolean }[] = [
    { key: 'vocals_mp3', label: 'Vocals (MP3)', primary: true },
    { key: 'vocals_wav', label: 'Vocals (WAV)' },
    { key: 'music_mp3', label: 'Music (MP3)' },
    ...(job.is_video && job.downloads.video ? [{ key: 'video', label: 'Video with vocals only (MP4)' }] : []),
  ].filter((d) => job.downloads[d.key])

  const removeFiles = async () => {
    await deleteJob(job.id)
    onReset()
  }

  return (
    <div className="panel">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white">Your vocals are ready</h2>
          <p className="mt-1 truncate text-sm text-zinc-400">
            {job.source_name}
            {formatDuration(job.duration_sec)}
          </p>
        </div>
        <button type="button" onClick={onReset} className="btn-ghost">
          Process another file
        </button>
      </div>

      <WaveformAB job={job} />

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {downloads.map((d) => (
          <a
            key={d.key}
            href={apiUrl(job.downloads[d.key])}
            download
            className={
              d.primary
                ? 'btn-primary col-span-2 sm:col-span-1'
                : 'btn-ghost justify-center col-span-1'
            }
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16" />
            </svg>
            {d.label}
          </a>
        ))}
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-zinc-800 pt-4 text-xs text-zinc-500">
        <span>Files are deleted automatically after 24 hours.</span>
        <button type="button" onClick={() => void removeFiles()} className="transition hover:text-zinc-300">
          Delete my files now
        </button>
      </div>
    </div>
  )
}
