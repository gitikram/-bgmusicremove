/** Live job progress: stage checklist plus a percentage bar fed by the backend. */

import type { Job } from '../api'

const STAGES = [
  { key: 'ingest', uploadLabel: 'Reading file', urlLabel: 'Fetching audio from URL' },
  { key: 'normalize', uploadLabel: 'Decoding & normalizing', urlLabel: 'Decoding & normalizing' },
  { key: 'separate', uploadLabel: 'AI vocal separation', urlLabel: 'AI vocal separation' },
  { key: 'encode', uploadLabel: 'Encoding outputs', urlLabel: 'Encoding outputs' },
] as const

export default function ProgressView({ job }: { job: Job }) {
  const activeIndex = Math.max(0, STAGES.findIndex((s) => s.key === job.stage))

  return (
    <div className="panel">
      <div className="mb-5">
        <h2 className="text-lg font-semibold">Removing the background music…</h2>
        <p className="mt-1 truncate text-sm text-zinc-400">{job.source_name}</p>
      </div>

      <ol className="mb-6 space-y-3">
        {STAGES.map((stage, i) => {
          const done = job.status === 'done' || i < activeIndex
          const active = job.status !== 'done' && i === activeIndex
          return (
            <li key={stage.key} className="flex items-center gap-3 text-sm">
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs ${
                  done
                    ? 'border-brand-500 bg-brand-600 text-white'
                    : active
                      ? 'border-brand-500 text-brand-400'
                      : 'border-zinc-700 text-zinc-600'
                }`}
              >
                {done ? '✓' : i + 1}
              </span>
              <span className={done ? 'text-zinc-300' : active ? 'font-medium text-white' : 'text-zinc-600'}>
                {job.source === 'url' ? stage.urlLabel : stage.uploadLabel}
              </span>
              {active && (
                <span className="ml-auto flex items-center gap-2 text-xs text-brand-400">
                  <span className="h-2 w-2 animate-ping rounded-full bg-brand-500" />
                  working
                </span>
              )}
            </li>
          )
        })}
      </ol>

      <div className="h-2.5 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full transition-all ${job.stage === 'separate' ? 'shimmer' : 'bg-brand-500'}`}
          style={{ width: `${Math.max(3, job.progress)}%` }}
        />
      </div>
      <p className="mt-2 text-right text-xs text-zinc-500">{job.progress}%</p>
    </div>
  )
}
