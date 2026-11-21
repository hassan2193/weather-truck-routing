import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { RISK_LEVELS } from '../lib/risk'

// Display copy of the thresholds enforced by the backend risk engine (backend/risk_engine/rules.py).
const ROWS = [
  ['Wind', ['< 25 mph', '25 – <35', '35 – <45', '45 – <55', '≥ 55 mph']],
  ['Rain', ['< 0.10 in/hr', '0.10 – <0.25', '0.25 – <0.50', '0.50 – 1.00', '> 1.00']],
  ['Snow', ['< 0.5 in/hr', '0.5 – <1.0', '1.0 – <2.0', '2.0 – 3.0', '> 3.0']],
]

export default function MethodologyModal({ open, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const dlg = ref.current
    if (!dlg) return
    if (open && !dlg.open) dlg.showModal()
    if (!open && dlg.open) dlg.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto max-h-[90vh] w-[min(720px,94vw)] overflow-auto rounded-2xl p-0 text-slate-800 shadow-2xl backdrop:bg-slate-900/50"
    >
      <div className="p-6">
        <div className="flex items-start justify-between">
          <h2 className="text-lg font-bold text-slate-900">How risk and recommendations are calculated</h2>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-slate-500 hover:bg-slate-100" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <section className="mt-4 space-y-2 text-sm text-slate-600">
          <p>
            Each route is sampled at your chosen interval (10, 25 or 50 miles) plus the origin and destination. Weather is taken from the
            forecast hour matching the truck’s <strong>estimated arrival time</strong> at each checkpoint (ETA built from the routing
            provider’s per-segment drive times). A checkpoint’s risk is the highest of its wind, rain and snow classes.
          </p>
        </section>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse text-center text-xs">
            <thead>
              <tr>
                <th className="border border-slate-200 bg-slate-50 p-2 text-left">Condition</th>
                {RISK_LEVELS.map((r) => (
                  <th key={r.label} className="border border-slate-200 p-2" style={{ background: `${r.color}33` }}>
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([name, cells]) => (
                <tr key={name}>
                  <th className="border border-slate-200 bg-slate-50 p-2 text-left">{name}</th>
                  {cells.map((c) => (
                    <td key={c} className="border border-slate-200 p-2 tabular-nums">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Boundary rule: bands are lower-bound inclusive (35 mph is High; 0.25 in/hr rain is High). Rain 1.00 and snow 3.0 are the top of
          Severe because No Travel is defined as strictly “greater than”.
        </p>

        <h3 className="mt-5 text-sm font-bold text-slate-900">Load rules</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Wind ≥ 55 mph → <strong>No Travel</strong> for any load.</li>
          <li>Wind 45–54 mph and load &gt; 30,000 lb → <strong>No Travel</strong>.</li>
          <li>Wind 35–44 mph and load &gt; 40,000 lb → <strong>Severe</strong>.</li>
        </ul>

        <h3 className="mt-5 text-sm font-bold text-slate-900">Recommendation order</h3>
        <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-slate-600">
          <li>Fewest <strong>Severe</strong> miles</li>
          <li>Fewest <strong>High</strong> miles</li>
          <li>Lowest distance-weighted <strong>average risk</strong> (Low 0 … No Travel 4)</li>
          <li>Shortest <strong>travel time</strong></li>
        </ol>
        <p className="mt-2 text-sm text-slate-600">
          Risk miles use the length of road each checkpoint represents (not a checkpoint count). A route with any No Travel segment is
          never recommended over one without.
        </p>

        <h3 className="mt-5 text-sm font-bold text-slate-900">Data and limits</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>Routes: Valhalla truck routing (OpenStreetMap). Weather: Open-Meteo hourly forecast (16-day horizon). Geocoding: Photon / Nominatim.</li>
          <li>Where a checkpoint’s arrival time is beyond the forecast, it is shown as unavailable and excluded from risk totals.</li>
          <li>ETAs assume continuous driving at the provider’s typical truck speeds with no live traffic, breaks or hours-of-service stops.</li>
          <li>Wind is 10 m sustained speed; rain and snow are hourly intensities. Snow is snowfall depth per hour, not liquid equivalent.</li>
        </ul>
      </div>
    </dialog>
  )
}
