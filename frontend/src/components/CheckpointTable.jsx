import { useEffect, useRef } from 'react'
import { WEATHER_STATUS_TEXT, formatCompact, formatMiles, formatRate, formatWind, timeZoneLabel } from '../lib/format'
import { ROUTE_COLORS } from '../lib/risk'
import RiskBadge from './RiskBadge'

export default function CheckpointTable({ route, views, selectedSequence, onSelect, snapshot }) {
  const rowRefs = useRef(new Map())
  useEffect(() => {
    if (selectedSequence != null) rowRefs.current.get(selectedSequence)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedSequence])

  const color = ROUTE_COLORS[route.index % ROUTE_COLORS.length]
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="cp-title">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <h2 id="cp-title" className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <span className="grid h-5 w-5 place-items-center rounded text-[11px] text-white" style={{ background: color }}>
            {route.label}
          </span>
          Checkpoint details
          <span className="font-normal text-slate-500">
            · {route.checkpoints.length} checkpoints · {formatMiles(route.distance_mi)}
          </span>
        </h2>
        <p className="text-xs text-slate-500">
          {snapshot ? 'Showing forecast at the selected hour for every checkpoint' : 'Weather evaluated at each checkpoint’s estimated arrival'}
          {' · times in '}
          {timeZoneLabel()}
        </p>
      </header>
      <div className="max-h-[22rem] overflow-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2">Mile</th>
              <th className="px-2 py-2">{snapshot ? 'Forecast time' : 'ETA'}</th>
              <th className="px-2 py-2">Wind</th>
              <th className="px-2 py-2">Rain</th>
              <th className="px-2 py-2">Snow</th>
              <th className="px-4 py-2">Risk</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {route.checkpoints.map((cp, i) => {
              const v = views[i]
              const selected = selectedSequence === cp.sequence
              return (
                <tr
                  key={cp.sequence}
                  ref={(el) => (el ? rowRefs.current.set(cp.sequence, el) : rowRefs.current.delete(cp.sequence))}
                  onClick={() => onSelect(cp.sequence)}
                  className={`cursor-pointer transition-colors hover:bg-slate-50 ${selected ? 'bg-brand-50' : ''}`}
                  aria-selected={selected}
                >
                  <td className="px-4 py-2 font-medium tabular-nums text-slate-900">{formatMiles(cp.distance_mi, 0)}</td>
                  <td className="px-2 py-2 text-slate-600 tabular-nums">{formatCompact(v.time)}</td>
                  {v.available ? (
                    <>
                      <td className="px-2 py-2 tabular-nums">{formatWind(v.wind)}</td>
                      <td className="px-2 py-2 tabular-nums">{formatRate(v.rain)}</td>
                      <td className="px-2 py-2 tabular-nums">{formatRate(v.snow)}</td>
                    </>
                  ) : (
                    <td colSpan={3} className="px-2 py-2 text-xs text-slate-400">
                      {WEATHER_STATUS_TEXT[v.status] ?? 'Unavailable'}
                    </td>
                  )}
                  <td className="px-4 py-2">
                    <RiskBadge level={v.risk} available={v.available} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
