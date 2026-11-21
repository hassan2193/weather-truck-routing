import { AlertTriangle, CloudRain, Snowflake, Wind } from 'lucide-react'
import { WEATHER_STATUS_TEXT, formatDateTime, formatMiles, formatRate, formatWind } from '../lib/format'
import RiskBadge from './RiskBadge'

function Row({ icon: Icon, label, value, level }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <dt className="flex items-center gap-1.5 text-slate-500">
        <Icon size={14} /> {label}
      </dt>
      <dd className="flex items-center gap-2 font-medium text-slate-800">
        {value}
        {level && <span className="text-[11px] font-normal text-slate-500">({level})</span>}
      </dd>
    </div>
  )
}

/** Details for one checkpoint, shown in the map popup. */
export default function CheckpointDetails({ route, checkpoint, view }) {
  const snapshot = view.mode === 'snapshot'
  return (
    <div className="text-[13px] leading-snug">
      <div className="flex items-start justify-between gap-2 pr-4">
        <div>
          <p className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">
            Route {route.label} · checkpoint {checkpoint.sequence + 1}
          </p>
          <p className="text-base font-semibold text-slate-900">{formatMiles(checkpoint.distance_mi, 1)} from start</p>
        </div>
        <RiskBadge level={view.risk} available={view.available} />
      </div>

      <p className="mt-1.5 text-slate-600">
        {snapshot ? 'Forecast for ' : 'ETA '}
        <span className="font-medium text-slate-800">{formatDateTime(view.time)}</span>
      </p>

      {view.available ? (
        <dl className="mt-2 divide-y divide-slate-100 border-t border-slate-100">
          <Row icon={Wind} label="Wind" value={formatWind(view.wind)} level={!snapshot ? checkpoint.risk?.wind : null} />
          {view.gust != null && <Row icon={Wind} label="Gusts" value={formatWind(view.gust)} />}
          <Row icon={CloudRain} label="Rain" value={formatRate(view.rain)} level={!snapshot ? checkpoint.risk?.rain : null} />
          <Row icon={Snowflake} label="Snow" value={formatRate(view.snow)} level={!snapshot ? checkpoint.risk?.snow : null} />
        </dl>
      ) : (
        <p className="mt-2 flex items-start gap-2 rounded-md bg-slate-50 p-2 text-slate-600">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {WEATHER_STATUS_TEXT[view.status] ?? 'Weather unavailable for this time.'}
        </p>
      )}

      {view.loadRule && (
        <p className="mt-2 rounded-md bg-red-50 p-2 text-xs text-red-800">Load rule applied: {view.loadRule}.</p>
      )}
      {!snapshot && view.available && view.risk > 0 && view.drivers.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-slate-600">
          {view.drivers.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {!snapshot && checkpoint.weather.valid_time && (
        <p className="mt-2 text-[11px] text-slate-400">Forecast hour used: {formatDateTime(checkpoint.weather.valid_time)}</p>
      )}
    </div>
  )
}
