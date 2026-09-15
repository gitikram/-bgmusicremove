/** A/B waveform player: compare the original mix against the isolated vocals (and the removed music). */

import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { apiUrl, type AudioKind, type Job } from '../api'

const TRACKS: { key: AudioKind; label: string; wave: string; progress: string }[] = [
  { key: 'original', label: 'Original mix', wave: '#52525b', progress: '#e4e4e7' },
  { key: 'vocals', label: 'Vocals — kept', wave: '#fda4af', progress: '#e11d48' },
  { key: 'music', label: 'Music — removed', wave: '#3f3f46', progress: '#a1a1aa' },
]

function formatTime(sec: number): string {
  if (!Number.isFinite(sec)) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function WaveformAB({ job }: { job: Job }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WaveSurfer | null>(null)
  const resumeRef = useRef<{ time: number; playing: boolean }>({ time: 0, playing: false })

  const [active, setActive] = useState<AudioKind>('vocals')
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [ready, setReady] = useState(false)

  // Rebuild the wavesurfer instance whenever the selected track changes,
  // preserving the playhead position and play state for a true A/B comparison.
  useEffect(() => {
    if (!containerRef.current) return
    setReady(false)
    const resume = resumeRef.current

    const ws = WaveSurfer.create({
      container: containerRef.current,
      url: apiUrl(job.audio[active]),
      height: 96,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      cursorWidth: 2,
      cursorColor: '#fafafa',
      normalize: true,
      waveColor: TRACKS.find((t) => t.key === active)!.wave,
      progressColor: TRACKS.find((t) => t.key === active)!.progress,
    })
    wsRef.current = ws

    ws.on('ready', () => {
      setReady(true)
      setDuration(ws.getDuration())
      if (resume.time > 0) ws.setTime(Math.min(resume.time, ws.getDuration()))
      if (resume.playing) void ws.play()
      resumeRef.current = { time: 0, playing: false }
    })
    ws.on('audioprocess', () => setTime(ws.getCurrentTime()))
    ws.on('timeupdate', () => setTime(ws.getCurrentTime()))
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => setPlaying(false))
    ws.on('error', () => setReady(true))

    return () => {
      ws.destroy()
      wsRef.current = null
    }
  }, [active, job.audio])

  // Stop playback when leaving the results view.
  useEffect(() => () => wsRef.current?.stop(), [])

  const switchTrack = (key: AudioKind) => {
    if (key === active) return
    const ws = wsRef.current
    resumeRef.current = { time: ws?.getCurrentTime() ?? 0, playing: ws?.isPlaying() ?? false }
    setPlaying(resumeRef.current.playing)
    setActive(key)
  }

  const togglePlay = () => {
    const ws = wsRef.current
    if (!ws || !ready) return
    void ws.playPause()
  }

  return (
    <div>
      {/* Track selector */}
      <div className="mb-4 inline-flex rounded-xl border border-zinc-800 bg-zinc-950 p-1">
        {TRACKS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => switchTrack(t.key)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition sm:text-sm ${
              active === t.key ? (t.key === 'vocals' ? 'bg-brand-600 text-white' : 'bg-zinc-700 text-white') : 'text-zinc-400 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Waveform */}
      <div className="rounded-2xl border border-zinc-800 bg-zinc-950 p-4">
        <div ref={containerRef} />
        {!ready && <p className="mt-2 text-center text-xs text-zinc-500">Loading audio…</p>}
      </div>

      {/* Transport */}
      <div className="mt-4 flex items-center gap-4">
        <button
          type="button"
          onClick={togglePlay}
          disabled={!ready}
          aria-label={playing ? 'Pause' : 'Play'}
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white transition hover:bg-brand-500 disabled:opacity-40"
        >
          {playing ? (
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" className="ml-0.5 h-5 w-5" fill="currentColor">
              <path d="M8 5.5v13a1 1 0 001.54.84l10-6.5a1 1 0 000-1.68l-10-6.5A1 1 0 008 5.5z" />
            </svg>
          )}
        </button>
        <span className="font-mono text-sm text-zinc-400">
          {formatTime(time)} / {formatTime(duration)}
        </span>
        <span className="ml-auto hidden text-xs text-zinc-500 sm:block">Click the waveform to seek</span>
      </div>
    </div>
  )
}
