import { ArrowDownUp, CalendarClock, Flag, Loader2, Navigation, Scale, Search } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { nextHour, toLocalInputValue } from '../lib/format'
import { INTERVALS, MAX_LOAD_LB, validateTrip } from '../lib/validation'
import PlaceInput from './PlaceInput'

const LOAD_PRESETS = [
  { label: 'Empty', value: 0 },
  { label: '25k', value: 25000 },
  { label: '35k', value: 35000 },
  { label: '45k', value: 45000 },
]

const toPayloadPlace = (v) => (v.place ? { label: v.place.label, lat: v.place.lat, lon: v.place.lon } : v.text.trim())

function loadHint(load) {
  const n = Number(load)
  if (!Number.isFinite(n)) return null
  if (n > 40000) return 'Over 40,000 lb: wind ≥35 mph is Severe and wind ≥45 mph is No Travel.'
  if (n > 30000) return 'Over 30,000 lb: wind ≥45 mph is No Travel (and ≥55 mph for any load).'
  return 'Load rules: wind ≥55 mph is No Travel for any load.'
}

export default function TripForm({ onSubmit, loading, serverErrors = {} }) {
  const ids = { departure: useId(), load: useId() }
  const [origin, setOrigin] = useState({ text: '', place: null })
  const [destination, setDestination] = useState({ text: '', place: null })
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextHour()))
  const [loadLb, setLoadLb] = useState('42000')
  const [interval, setIntervalMiles] = useState(25)
  const [touched, setTouched] = useState(false)

  const clientErrors = useMemo(
    () => validateTrip({ origin, destination, departure, loadLb, interval }),
    [origin, destination, departure, loadLb, interval],
  )
  const errors = { ...serverErrors, ...(touched ? clientErrors : {}) }

  const submit = (e) => {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(clientErrors).length) return
    onSubmit({
      origin: toPayloadPlace(origin),
      destination: toPayloadPlace(destination),
      departure_time: new Date(departure).toISOString(),
      load_weight_lb: Number(loadLb),
      interval_miles: Number(interval),
    })
  }

  const swap = () => {
    setOrigin(destination)
    setDestination(origin)
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="relative space-y-3">
        <PlaceInput
          label="Origin"
          value={origin}
          onChange={setOrigin}
          error={errors.origin}
          placeholder="City, address or ZIP"
          icon={Navigation}
          accent="#16a34a"
        />
        <button
          type="button"
          onClick={swap}
          className="absolute top-[46%] right-3 z-10 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm hover:text-brand-600"
          aria-label="Swap origin and destination"
          title="Swap"
        >
          <ArrowDownUp size={14} />
        </button>
        <PlaceInput
          label="Destination"
          value={destination}
          onChange={setDestination}
          error={errors.destination}
          placeholder="City, address or ZIP"
          icon={Flag}
          accent="#0f172a"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div>
          <label htmlFor={ids.departure} className="mb-1 block text-xs font-semibold text-slate-600">
            Departure
          </label>
          <div className="relative">
            <CalendarClock size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
            <input
              id={ids.departure}
              type="datetime-local"
              value={departure}
              onChange={(e) => setDeparture(e.target.value)}
              aria-invalid={Boolean(errors.departure)}
              className={`w-full rounded-lg border bg-white py-2 pr-2 pl-9 text-sm shadow-xs outline-none focus:ring-2 ${
                errors.departure ? 'border-red-400 focus:ring-red-200' : 'border-slate-300 focus:border-brand-500 focus:ring-brand-100'
              }`}
            />
          </div>
          {errors.departure && <p className="mt-1 text-xs text-red-600">{errors.departure}</p>}
        </div>

        <div>
          <label htmlFor={ids.load} className="mb-1 block text-xs font-semibold text-slate-600">
            Load weight
          </label>
          <div className="relative">
            <Scale size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
            <input
              id={ids.load}
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_LOAD_LB}
              step={500}
              value={loadLb}
              onChange={(e) => setLoadLb(e.target.value)}
              aria-invalid={Boolean(errors.loadLb || errors.load_weight_lb)}
              className={`w-full rounded-lg border bg-white py-2 pr-10 pl-9 text-sm shadow-xs outline-none focus:ring-2 ${
                errors.loadLb || errors.load_weight_lb ? 'border-red-400 focus:ring-red-200' : 'border-slate-300 focus:border-brand-500 focus:ring-brand-100'
              }`}
            />
            <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-slate-400">lb</span>
          </div>
          {(errors.loadLb || errors.load_weight_lb) && <p className="mt-1 text-xs text-red-600">{errors.loadLb || errors.load_weight_lb}</p>}
        </div>
      </div>

      <div className="-mt-1 flex flex-wrap items-center gap-1.5">
        {LOAD_PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            onClick={() => setLoadLb(String(p.value))}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
              Number(loadLb) === p.value ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            {p.label}
          </button>
        ))}
        <span className="text-[11px] leading-tight text-slate-500">{loadHint(loadLb)}</span>
      </div>

      <fieldset>
        <legend className="mb-1 text-xs font-semibold text-slate-600">Weather checkpoint every</legend>
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1" role="radiogroup">
          {INTERVALS.map((v) => (
            <label
              key={v}
              className={`cursor-pointer rounded-md py-1.5 text-center text-sm font-medium transition ${
                Number(interval) === v ? 'bg-white text-brand-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <input type="radio" name="interval" value={v} checked={Number(interval) === v} onChange={() => setIntervalMiles(v)} className="sr-only" />
              {v} mi
            </label>
          ))}
        </div>
      </fieldset>

      <button
        type="submit"
        disabled={loading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-brand-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-wait disabled:opacity-70"
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
        {loading ? 'Analysing…' : 'Find safest route'}
      </button>
      <p className="text-center text-[11px] text-slate-400">Times are shown in your browser’s time zone.</p>
    </form>
  )
}
