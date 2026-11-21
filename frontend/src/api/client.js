const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { code = 'request_error', status = 0, details = {} } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

async function request(path, { method = 'GET', body, signal, timeoutMs = 120000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs)
  signal?.addEventListener('abort', () => controller.abort(signal.reason))
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError' && signal?.aborted) throw err // caller cancelled
    if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
      throw new ApiError('The request took too long. Please try again.', { code: 'timeout' })
    }
    throw new ApiError('Cannot reach the server. Check your connection and try again.', { code: 'network' })
  } finally {
    clearTimeout(timer)
  }

  let data = null
  try {
    data = await response.json()
  } catch {
    /* non-JSON body */
  }
  if (!response.ok) {
    const err = data?.error
    throw new ApiError(err?.message || `Request failed (HTTP ${response.status}).`, {
      code: err?.code || 'request_error',
      status: response.status,
      details: err?.details || {},
    })
  }
  return data
}

export const analyzeTrip = (payload, signal) =>
  request('/api/routes/analyze/', { method: 'POST', body: payload, signal })

export const fetchForecast = (routeId, signal) => request(`/api/routes/${routeId}/forecast/`, { signal })

export const searchPlaces = (query, signal) =>
  request(`/api/geocode/?q=${encodeURIComponent(query)}`, { signal, timeoutMs: 15000 })

export const fetchHealth = (signal) => request('/api/health/', { signal, timeoutMs: 10000 })
