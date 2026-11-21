// Risk level presentation. The *classification* lives in the backend risk engine;
// the frontend only maps the numeric level it receives to colours and labels.

export const RISK_LEVELS = [
  { level: 0, label: 'Low', slug: 'low', color: '#22c55e', badge: 'bg-green-100 text-green-800 ring-green-600/20' },
  { level: 1, label: 'Moderate', slug: 'moderate', color: '#facc15', badge: 'bg-yellow-100 text-yellow-800 ring-yellow-600/20' },
  { level: 2, label: 'High', slug: 'high', color: '#f97316', badge: 'bg-orange-100 text-orange-800 ring-orange-600/20' },
  { level: 3, label: 'Severe', slug: 'severe', color: '#ef4444', badge: 'bg-red-100 text-red-800 ring-red-600/20' },
  { level: 4, label: 'No Travel', slug: 'no_travel', color: '#7f1d1d', badge: 'bg-red-900 text-white ring-red-900/30' },
]

export const UNAVAILABLE = {
  level: null,
  label: 'Unavailable',
  slug: 'unavailable',
  color: '#94a3b8',
  badge: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

export function riskMeta(level) {
  return level == null ? UNAVAILABLE : RISK_LEVELS[level] ?? UNAVAILABLE
}

const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))

const RAMP = RISK_LEVELS.map((r) => hexToRgb(r.color))

/** Colour for a continuous risk score in [0, 4], interpolating between the level colours. */
export function rampRgb(value) {
  const v = Math.min(4, Math.max(0, value))
  const i = Math.min(3, Math.floor(v))
  const t = v - i
  const a = RAMP[i]
  const b = RAMP[i + 1]
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

export const ROUTE_COLORS = ['#2563eb', '#7c3aed', '#0e7490']
