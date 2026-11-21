export const INTERVALS = [10, 25, 50]
export const MAX_LOAD_LB = 120000
export const MAX_FORECAST_DAYS = 16

const HOUR_MS = 3600 * 1000

/**
 * Validate the trip form before any request is sent.
 * Mirrors the backend rules; the server remains the source of truth.
 */
export function validateTrip({ origin, destination, departure, loadLb, interval }, now = new Date()) {
  const errors = {}
  if (!origin || origin.text.trim().length < 2) errors.origin = 'Enter a starting location.'
  if (!destination || destination.text.trim().length < 2) errors.destination = 'Enter a destination.'
  if (
    !errors.origin &&
    !errors.destination &&
    origin.text.trim().toLowerCase() === destination.text.trim().toLowerCase()
  ) {
    errors.destination = 'Destination must differ from the origin.'
  }

  const when = departure ? new Date(departure) : null
  if (!when || Number.isNaN(when.getTime())) {
    errors.departure = 'Choose a departure date and time.'
  } else if (when.getTime() < now.getTime() - HOUR_MS) {
    errors.departure = 'Departure cannot be in the past.'
  } else if (when.getTime() > now.getTime() + MAX_FORECAST_DAYS * 24 * HOUR_MS) {
    errors.departure = `Forecasts only extend ${MAX_FORECAST_DAYS} days ahead.`
  }

  const load = Number(loadLb)
  if (loadLb === '' || loadLb == null || !Number.isFinite(load) || !Number.isInteger(load)) {
    errors.loadLb = 'Enter the load weight in whole pounds.'
  } else if (load < 0) {
    errors.loadLb = 'Load weight cannot be negative.'
  } else if (load > MAX_LOAD_LB) {
    errors.loadLb = `Load weight cannot exceed ${MAX_LOAD_LB.toLocaleString()} lb.`
  }

  if (!INTERVALS.includes(Number(interval))) errors.interval = 'Choose 10, 25 or 50 miles.'
  return errors
}
