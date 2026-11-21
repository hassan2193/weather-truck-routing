import { RISK_LEVELS, UNAVAILABLE } from '../lib/risk'

const SEGMENTS = [
  ['low_miles', RISK_LEVELS[0]],
  ['moderate_miles', RISK_LEVELS[1]],
  ['high_miles', RISK_LEVELS[2]],
  ['severe_miles', RISK_LEVELS[3]],
  ['no_travel_miles', RISK_LEVELS[4]],
  ['unknown_miles', UNAVAILABLE],
]

/** Stacked bar showing how many route miles fall in each risk class. */
export default function RiskBar({ metrics, distance }) {
  const total = distance || 1
  const title = SEGMENTS.map(([key, meta]) => `${meta.label}: ${metrics[key].toFixed(1)} mi`).join('\n')
  return (
    <div
      className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-100 ring-1 ring-black/5"
      role="img"
      aria-label={`Miles by risk level. ${title.replaceAll('\n', '; ')}`}
      title={title}
    >
      {SEGMENTS.map(([key, meta]) => {
        const pct = (metrics[key] / total) * 100
        return pct > 0 ? <div key={key} style={{ width: `${pct}%`, background: meta.color }} /> : null
      })}
    </div>
  )
}
