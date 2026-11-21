import { useEffect, useState } from 'react'
import { fetchForecast } from '../api/client'

// Forecasts are keyed by route id and kept for the session: switching routes or
// moving the slider never re-requests data we already have.
const cache = new Map()
const inflight = new Map()

function load(routeId) {
  if (cache.has(routeId)) return Promise.resolve(cache.get(routeId))
  if (!inflight.has(routeId)) {
    const p = fetchForecast(routeId)
      .then((data) => {
        cache.set(routeId, data)
        return data
      })
      .finally(() => inflight.delete(routeId))
    inflight.set(routeId, p)
  }
  return inflight.get(routeId)
}

/**
 * Loads the 0-48 h corridor forecast for each route id (the selected route first),
 * so the slider can update every route's checkpoints without further requests.
 * Returns `{ [routeId]: { data, error, loading } }`.
 */
export function useForecasts(routeIds, selectedId) {
  const key = routeIds.join(',')
  const [errors, setErrors] = useState({})
  const [, bump] = useState(0)

  useEffect(() => {
    let cancelled = false
    const ordered = [selectedId, ...routeIds.filter((id) => id !== selectedId)].filter(Boolean)
    ordered.forEach((id) => {
      if (cache.has(id)) return
      load(id)
        .then(() => !cancelled && bump((n) => n + 1))
        .catch((error) => !cancelled && setErrors((e) => ({ ...e, [id]: error })))
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, selectedId])

  const result = {}
  routeIds.forEach((id) => {
    const data = cache.get(id) ?? null
    result[id] = { data, error: data ? null : errors[id] ?? null, loading: !data && !errors[id] }
  })
  return result
}
