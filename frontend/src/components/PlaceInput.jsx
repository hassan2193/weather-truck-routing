import { Loader2, MapPin } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { searchPlaces } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'

/**
 * Address field with typeahead. `value` is `{ text, place }`: `place` is set once the
 * user picks a suggestion; free text without a pick is geocoded by the server.
 */
export default function PlaceInput({ label, value, onChange, error, placeholder, icon: Icon = MapPin, accent }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  // Latest completed search: {query, results, error}. `loading` is derived, not stored.
  const [search, setSearch] = useState({ query: '', results: [], error: null })
  const [active, setActive] = useState(-1)
  const wrapper = useRef(null)
  const debounced = useDebounced(value.text, 350)

  const query = debounced.trim()
  const enabled = open && !value.place && query.length >= 3

  useEffect(() => {
    if (!enabled) return undefined
    const ctrl = new AbortController()
    searchPlaces(query, ctrl.signal)
      .then((data) => {
        setSearch({ query, results: data.results, error: null })
        setActive(-1)
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) setSearch({ query, results: [], error: err.message })
      })
    return () => ctrl.abort()
  }, [enabled, query])

  useEffect(() => {
    const close = (e) => !wrapper.current?.contains(e.target) && setOpen(false)
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [])

  const choose = (place) => {
    onChange({ text: place.label, place })
    setOpen(false)
  }

  const onKeyDown = (e) => {
    if (!showList || !shown.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % shown.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i <= 0 ? shown.length - 1 : i - 1))
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault()
      choose(shown[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const loading = enabled && search.query !== query
  const shown = enabled && search.query === query ? search.results : []
  const searchError = enabled && search.query === query ? search.error : null
  const showList = enabled && (shown.length > 0 || loading || Boolean(searchError))

  return (
    <div ref={wrapper} className="relative">
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-slate-600">
        {label}
      </label>
      <div className="relative">
        <Icon size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" style={{ color: accent }} />
        <input
          id={id}
          type="text"
          autoComplete="off"
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${id}-list`}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-err` : undefined}
          value={value.text}
          placeholder={placeholder}
          onChange={(e) => {
            onChange({ text: e.target.value, place: null })
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className={`w-full rounded-lg border bg-white py-2 pr-9 pl-9 text-sm shadow-xs transition outline-none placeholder:text-slate-400 focus:ring-2 ${
            error ? 'border-red-400 focus:ring-red-200' : 'border-slate-300 focus:border-brand-500 focus:ring-brand-100'
          }`}
        />
        {loading && <Loader2 size={14} className="absolute top-1/2 right-3 -translate-y-1/2 animate-spin text-slate-400" />}
      </div>
      {error && (
        <p id={`${id}-err`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
      {showList && (
        <ul
          id={`${id}-list`}
          role="listbox"
          className="absolute z-30 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-xl"
        >
          {searchError && <li className="px-3 py-2 text-xs text-red-600">{searchError}</li>}
          {!searchError && loading && !shown.length && <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>}
          {shown.map((r, i) => (
            <li
              key={`${r.lat},${r.lon}`}
              role="option"
              aria-selected={i === active}
              onPointerDown={(e) => {
                e.preventDefault()
                choose(r)
              }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-2 ${i === active ? 'bg-brand-50 text-brand-900' : 'text-slate-700'}`}
            >
              {r.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
