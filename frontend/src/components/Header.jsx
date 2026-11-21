import { BookOpen, LayoutDashboard, Truck } from 'lucide-react'

const STATUS = {
  ok: { dot: 'bg-green-400', text: 'All systems operational' },
  degraded: { dot: 'bg-amber-400', text: 'Degraded' },
  offline: { dot: 'bg-red-400', text: 'API unreachable' },
  checking: { dot: 'bg-slate-400 animate-pulse', text: 'Checking…' },
}

export default function Header({ health, onOpenMethodology, weatherStats }) {
  const s = STATUS[health.status] ?? STATUS.checking
  const providers = health.data?.providers
  const tooltip = [
    `API: ${s.text}`,
    health.data && `Database: ${health.data.database.status} (${health.data.database.engine})`,
    providers && `Routing: ${providers.routing.name}`,
    providers && `Weather: ${providers.weather.name}`,
    providers && `Geocoding: ${providers.geocoding.name}`,
    weatherStats &&
      `Last analysis: ${weatherStats.checkpoints} checkpoints → ${weatherStats.unique_locations} weather locations (${weatherStats.cache_hits} cached, ${weatherStats.upstream_requests} requests)`,
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <header className="sticky top-0 z-[1200] bg-brand-900 text-white shadow-md">
      <div className="mx-auto flex h-14 max-w-[1800px] items-center justify-between gap-3 px-4">
        <a href="/" className="flex items-center gap-2.5" aria-label="HaulWise home">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/10 ring-1 ring-white/20">
            <Truck size={18} className="text-accent" />
          </span>
          <span className="leading-tight">
            <span className="block text-sm font-bold tracking-tight">HaulWise</span>
            <span className="hidden text-[11px] text-white/60 sm:block">Weather-aware truck routing</span>
          </span>
        </a>

        <nav className="flex items-center gap-1" aria-label="Primary">
          <a href="#planner" className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-white/90 hover:bg-white/10">
            <LayoutDashboard size={15} /> <span className="hidden sm:inline">Planner</span>
          </a>
          <button
            type="button"
            onClick={onOpenMethodology}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-white/90 hover:bg-white/10"
          >
            <BookOpen size={15} /> <span className="hidden sm:inline">Risk methodology</span>
          </button>
        </nav>

        <div
          className="flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium ring-1 ring-white/15"
          title={tooltip}
          role="status"
          aria-label={`System status: ${s.text}`}
        >
          <span className={`h-2 w-2 rounded-full ${s.dot}`} />
          <span className="hidden md:inline">{s.text}</span>
        </div>
      </div>
    </header>
  )
}
