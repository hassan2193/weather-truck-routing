import { AlertOctagon, CheckCircle2, Info } from 'lucide-react'
import { ROUTE_COLORS } from '../lib/risk'

export default function RecommendationCard({ analysis }) {
  const rec = analysis.recommendation
  const route = analysis.routes.find((r) => r.id === rec.route_id)
  const unsafe = rec.all_routes_unsafe
  const color = route ? ROUTE_COLORS[route.index % ROUTE_COLORS.length] : '#16a34a'

  return (
    <section
      className={`overflow-hidden rounded-xl border shadow-sm ${unsafe ? 'border-red-300 bg-red-50' : 'border-green-300 bg-green-50'}`}
      aria-labelledby="rec-title"
    >
      <div className="flex items-start gap-3 p-4">
        {unsafe ? (
          <AlertOctagon className="mt-0.5 shrink-0 text-red-700" size={22} />
        ) : (
          <CheckCircle2 className="mt-0.5 shrink-0 text-green-700" size={22} />
        )}
        <div className="min-w-0">
          <h2 id="rec-title" className={`flex items-center gap-2 text-sm font-bold ${unsafe ? 'text-red-900' : 'text-green-900'}`}>
            {unsafe ? 'No safe route found' : 'Recommended route'}
            <span className="grid h-5 min-w-5 place-items-center rounded px-1 text-xs text-white" style={{ background: color }}>
              {rec.route_label}
            </span>
          </h2>
          <p className={`mt-1 text-sm leading-snug ${unsafe ? 'text-red-900' : 'text-green-900'}`}>{rec.headline}</p>
          {rec.details.length > 0 && (
            <ul className={`mt-2 list-disc space-y-1 pl-4 text-xs leading-snug ${unsafe ? 'text-red-800' : 'text-green-800'}`}>
              {rec.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {rec.warnings.length > 0 && (
        <ul className="space-y-1 border-t border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
          {rec.warnings.map((w) => (
            <li key={w} className="flex gap-1.5">
              <Info size={13} className="mt-0.5 shrink-0" /> {w}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
