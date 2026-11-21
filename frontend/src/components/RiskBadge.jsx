import { riskMeta } from '../lib/risk'

export default function RiskBadge({ level, available = true, className = '' }) {
  const meta = riskMeta(available ? level : null)
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${meta.badge} ${className}`}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} aria-hidden />
      {meta.label}
    </span>
  )
}
