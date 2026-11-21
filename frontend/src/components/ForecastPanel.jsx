import { CloudSun, Loader2, Pause, Play, RotateCcw, StepBack, StepForward } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { formatDateTime, formatWind } from '../lib/format'
import { RISK_LEVELS, UNAVAILABLE, riskMeta } from '../lib/risk'
import { maxRiskByHour, riskCounts } from '../lib/views'

const MAX_HOUR = 48
const TICKS = [0, 12, 24, 36, 48]

export default function ForecastPanel({ forecast, loading, error, hour, onHourChange, showHeat, onToggleHeat, views }) {
  const [playing, setPlaying] = useState(false)
  const peaks = useMemo(() => maxRiskByHour(forecast), [forecast])
  const counts = useMemo(() => riskCounts(views), [views])
  const windPeak = useMemo(() => views.reduce((m, v) => (v.wind != null && v.wind > m ? v.wind : m), 0), [views])
  const snapshot = hour != null

  const hourRef = useRef(hour)
  useEffect(() => {
    hourRef.current = hour
  }, [hour])
  useEffect(() => {
    if (!playing) return undefined
    const id = setInterval(() => {
      const next = Math.min(MAX_HOUR, (hourRef.current ?? -1) + 1)
      hourRef.current = next
      onHourChange(next)
      if (next >= MAX_HOUR) setPlaying(false)
    }, 650)
    return () => clearInterval(id)
  }, [playing, onHourChange])

  const disabled = !forecast
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby="forecast-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="forecast-title" className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <CloudSun size={18} className="text-brand-500" /> Forecast timeline
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${snapshot ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-600'}`}
          >
            {snapshot ? 'Forecast snapshot' : 'Trip view (at ETA)'}
          </span>
        </h2>
        <div className="flex items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-slate-600">
            <input type="checkbox" checked={showHeat} onChange={(e) => onToggleHeat(e.target.checked)} className="peer sr-only" />
            <span className="relative h-5 w-9 rounded-full bg-slate-300 transition peer-checked:bg-brand-500 peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500 after:absolute after:top-0.5 after:left-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-4" />
            Heatmap
          </label>
          {snapshot && (
            <button
              type="button"
              onClick={() => {
                setPlaying(false)
                onHourChange(null)
              }}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw size={12} /> Back to trip view
            </button>
          )}
        </div>
      </div>

      {error && <p className="mt-3 rounded-md bg-red-50 p-2 text-xs text-red-800">Could not load the forecast: {error.message}</p>}

      <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-lg font-semibold text-slate-900">
            {snapshot ? formatDateTime(forecast?.hours[hour]) : 'Weather at each checkpoint’s ETA'}
          </p>
          <p className="text-xs text-slate-500">
            {snapshot
              ? `+${hour} h after the departure hour · every checkpoint and the heatmap show forecast weather at this moment`
              : 'Move the slider to see the forecast at one moment in time (0–48 h after departure).'}
          </p>
        </div>
        {loading && (
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <Loader2 size={13} className="animate-spin" /> Loading forecast…
          </span>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setPlaying((p) => !p)}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-900 text-white hover:bg-brand-700 disabled:opacity-40"
          aria-label={playing ? 'Pause forecast animation' : 'Play forecast animation'}
        >
          {playing ? <Pause size={16} /> : <Play size={16} className="translate-x-px" />}
        </button>
        <button
          type="button"
          disabled={disabled || (hour ?? 0) <= 0}
          onClick={() => onHourChange((h) => Math.max(0, (h ?? 1) - 1))}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          aria-label="Previous hour"
        >
          <StepBack size={14} />
        </button>
        <div className="relative min-w-0 flex-1">
          {/* worst-risk-per-hour strip: real forecast data behind the slider track */}
          <div className="absolute inset-x-1 top-1/2 flex h-3 -translate-y-1/2 overflow-hidden rounded-full ring-1 ring-black/10" aria-hidden>
            {Array.from({ length: MAX_HOUR + 1 }, (_, h) => (
              <div key={h} className="h-full flex-1" style={{ background: peaks[h] == null ? '#e2e8f0' : riskMeta(peaks[h]).color }} />
            ))}
          </div>
          <input
            type="range"
            min={0}
            max={MAX_HOUR}
            step={1}
            value={hour ?? 0}
            disabled={disabled}
            onChange={(e) => onHourChange(Number(e.target.value))}
            className={`hour-slider ${snapshot ? '' : 'opacity-60'}`}
            aria-label="Forecast hour after departure"
            aria-valuetext={snapshot ? `${hour} hours after departure` : 'Trip view'}
          />
          <div className="mt-0.5 flex justify-between px-1 text-[10px] text-slate-400">
            {TICKS.map((t) => (
              <span key={t}>{t === 0 ? 'Departure' : `+${t} h`}</span>
            ))}
          </div>
        </div>
        <button
          type="button"
          disabled={disabled || hour === MAX_HOUR}
          onClick={() => onHourChange((h) => Math.min(MAX_HOUR, (h ?? -1) + 1))}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          aria-label="Next hour"
        >
          <StepForward size={14} />
        </button>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">Strip colour = worst risk anywhere along the selected route in that hour.</p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {[...RISK_LEVELS, { ...UNAVAILABLE, level: 'unavailable' }].map((r) =>
          counts[r.level] > 0 ? (
            <span key={r.label} className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2 py-0.5 text-xs text-slate-700 ring-1 ring-slate-200">
              <span className="h-2 w-2 rounded-full" style={{ background: r.color }} />
              {counts[r.level]} {r.label}
            </span>
          ) : null,
        )}
        <span className="ml-auto text-xs text-slate-500">Peak wind {formatWind(windPeak)}</span>
      </div>
    </section>
  )
}
