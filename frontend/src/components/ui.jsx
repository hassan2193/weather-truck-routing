import { AlertCircle, Info, RefreshCw } from 'lucide-react'

export function ErrorBanner({ error, onRetry, title = 'Something went wrong' }) {
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
      <div className="flex gap-2.5">
        <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-600" />
        <div>
          <p className="font-semibold">{title}</p>
          <p className="mt-0.5 text-red-800">{error?.message || String(error)}</p>
          {error?.code && error.code !== 'request_error' && <p className="mt-1 text-[11px] text-red-700/70">Error code: {error.code}</p>}
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-white px-2.5 py-1 text-xs font-semibold text-red-700 ring-1 ring-red-200 hover:bg-red-100"
            >
              <RefreshCw size={12} /> Try again
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function WarningList({ warnings }) {
  if (!warnings?.length) return null
  return (
    <ul className="space-y-1.5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      {warnings.map((w) => (
        <li key={w} className="flex gap-2">
          <Info size={14} className="mt-0.5 shrink-0" /> {w}
        </li>
      ))}
    </ul>
  )
}

export function ResultsSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading results">
      <div className="skeleton h-28" />
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton h-44" />
      ))}
    </div>
  )
}

export function EmptyResults() {
  const steps = [
    ['1', 'Enter your trip', 'Origin, destination, departure time and load weight.'],
    ['2', 'We compare 3 routes', 'Truck-aware routing, weather sampled at your ETA at each checkpoint.'],
    ['3', 'Pick the safest', 'Fewest severe miles first, then high-risk miles, average risk and time.'],
  ]
  return (
    <ol className="space-y-3 rounded-xl border border-dashed border-slate-300 bg-white/60 p-4">
      {steps.map(([n, title, text]) => (
        <li key={n} className="flex gap-3">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-100 text-xs font-bold text-brand-700">{n}</span>
          <div>
            <p className="text-sm font-semibold text-slate-800">{title}</p>
            <p className="text-xs text-slate-500">{text}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}
