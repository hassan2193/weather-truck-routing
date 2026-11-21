export function formatDuration(seconds) {
  const minutes = Math.round(seconds / 60)
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`
}

export const formatMiles = (miles, digits = 0) =>
  `${Number(miles).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} mi`

const dateTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})
const compactDateTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})
const shortDateTime = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })

export const formatDateTime = (iso) => (iso ? dateTime.format(new Date(iso)) : '—')
export const formatCompact = (iso) => (iso ? compactDateTime.format(new Date(iso)) : '—')

/** e.g. "Asia/Kolkata (GMT+5:30)" - the zone every time in the UI is shown in. */
export function timeZoneLabel() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const abbr = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value
  return abbr ? `${zone} (${abbr})` : zone
}

export const formatShort = (iso) => (iso ? shortDateTime.format(new Date(iso)) : '—')

export const formatWind = (v) => (v == null ? '—' : `${v.toFixed(0)} mph`)
export const formatRate = (v) => (v == null ? '—' : `${v.toFixed(2)} in/hr`)

/** Value for an <input type="datetime-local"> in the browser's local time. */
export function toLocalInputValue(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function nextHour(now = new Date()) {
  const d = new Date(now)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d
}

export const WEATHER_STATUS_TEXT = {
  ok: 'Forecast available',
  beyond_forecast_horizon: 'Beyond forecast horizon (16 days)',
  before_forecast_start: 'Before forecast start',
  no_data: 'No data from weather provider',
  provider_error: 'Weather service error',
}
