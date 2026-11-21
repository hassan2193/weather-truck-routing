import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { RISK_LEVELS, ROUTE_COLORS, UNAVAILABLE } from '../../lib/risk'

export default function Legend({ showHeat }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="absolute bottom-3 left-3 z-[1000] max-w-[210px] rounded-lg bg-white/95 text-xs shadow-lg ring-1 ring-black/5 backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 font-semibold text-slate-700"
        aria-expanded={open}
      >
        Legend {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
      </button>
      {open && (
        <div className="space-y-2.5 px-3 pb-3">
          <div>
            <p className="mb-1 font-medium text-slate-500">Checkpoint risk</p>
            <ul className="space-y-1">
              {[...RISK_LEVELS, UNAVAILABLE].map((r) => (
                <li key={r.label} className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full ring-2 ring-white" style={{ background: r.color, boxShadow: '0 0 0 1px rgb(0 0 0 / .15)' }} />
                  {r.label}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-1 font-medium text-slate-500">Routes</p>
            <ul className="space-y-1">
              {ROUTE_COLORS.map((c, i) => (
                <li key={c} className="flex items-center gap-2">
                  <span className="h-1 w-5 rounded" style={{ background: c }} />
                  Route {'ABC'[i]}
                </li>
              ))}
            </ul>
          </div>
          {showHeat && (
            <div>
              <p className="mb-1 font-medium text-slate-500">Weather heatmap</p>
              <div
                className="h-2 rounded"
                style={{ background: `linear-gradient(90deg, ${RISK_LEVELS.map((r) => r.color).join(', ')})` }}
              />
              <div className="mt-0.5 flex justify-between text-[10px] text-slate-500">
                <span>Low</span>
                <span>No Travel</span>
              </div>
              <p className="mt-1 text-[10px] leading-snug text-slate-500">
                Interpolated from forecast samples within ~14 mi of the selected route.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
