import { AlertOctagon, Award, Clock, GitFork, Route as RouteIcon, TriangleAlert } from 'lucide-react'
import { formatDateTime, formatDuration, formatMiles, formatShort } from '../lib/format'
import { ROUTE_COLORS } from '../lib/risk'
import RiskBar from './RiskBar'

function Stat({ label, value, tone, title }) {
  return (
    <div title={title}>
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className={`text-sm font-semibold ${tone ?? 'text-slate-900'}`}>{value}</dd>
    </div>
  )
}

export default function RouteCard({ route, selected, onSelect }) {
  const color = ROUTE_COLORS[route.index % ROUTE_COLORS.length]
  const m = route.metrics
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-xl border bg-white p-3.5 text-left shadow-sm transition hover:shadow-md focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:outline-none ${
        selected ? 'border-transparent' : 'border-slate-200'
      }`}
      style={selected ? { boxShadow: `0 0 0 2px ${color}, 0 4px 12px rgb(0 0 0 / .08)` } : undefined}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg text-sm font-bold text-white" style={{ background: color }}>
            {route.label}
          </span>
          <div>
            <p className="text-sm font-semibold text-slate-900">Route {route.label}</p>
            <p className="line-clamp-1 text-xs text-slate-500" title={route.summary}>
              {route.summary}
              {route.has_toll ? ' · tolls' : ''}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          {route.is_recommended && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-800">
              <Award size={12} /> Recommended
            </span>
          )}
          {route.source === 'diversified' && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700"
              title="Found by asking the routing service to avoid sections of the other routes. It is a real truck route, recalculated end to end."
            >
              <GitFork size={12} /> Alternative corridor
            </span>
          )}
          {route.no_travel && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-900 px-2 py-0.5 text-[11px] font-semibold text-white">
              <AlertOctagon size={12} /> Unsafe · No Travel
            </span>
          )}
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2">
        <Stat label="Distance" value={formatMiles(route.distance_mi)} />
        <Stat label="Drive time" value={formatDuration(route.duration_s)} />
        <Stat label="Arrive" value={formatShort(route.arrival_time)} title={formatDateTime(route.arrival_time)} />
      </dl>

      <div className="mt-3">
        <RiskBar metrics={m} distance={route.distance_mi} />
        <dl className="mt-2.5 grid grid-cols-4 gap-2">
          <Stat label="Severe mi" value={m.severe_miles.toFixed(1)} tone={m.severe_miles > 0 ? 'text-red-600' : undefined} />
          <Stat label="High mi" value={m.high_miles.toFixed(1)} tone={m.high_miles > 0 ? 'text-orange-600' : undefined} />
          <Stat label="No Travel mi" value={m.no_travel_miles.toFixed(1)} tone={m.no_travel_miles > 0 ? 'text-red-900' : undefined} />
          <Stat label="Avg risk" value={m.average_risk == null ? '—' : `${m.average_risk.toFixed(2)}/4`} />
        </dl>
      </div>

      {m.weather_coverage < 1 && (
        <p className="mt-2 flex items-center gap-1 text-[11px] text-amber-700">
          <TriangleAlert size={12} /> Weather known for {(m.weather_coverage * 100).toFixed(0)}% of this route
        </p>
      )}
      {route.no_travel && route.no_travel_reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 rounded-md bg-red-50 p-2 text-[11px] leading-snug text-red-900">
          {route.no_travel_reasons.slice(0, 3).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <p className="mt-2 flex items-center gap-3 text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1">
          <RouteIcon size={11} /> {route.checkpoints.length} checkpoints
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock size={11} /> rank #{route.rank}
        </span>
      </p>
    </button>
  )
}
