// Derive what to display for a checkpoint / heat sample in the two forecast modes:
//   hour === null  -> "trip view": weather at the truck's estimated arrival time
//   hour = 0..48   -> "snapshot": weather at every location at departure hour + N

/** @returns display data for one checkpoint */
export function checkpointView(cp, forecast, hour) {
  const fc = forecast?.checkpoints?.[cp.sequence]
  if (hour == null || !fc) {
    return {
      mode: 'eta',
      time: cp.eta,
      status: cp.weather.status,
      available: cp.weather.status === 'ok',
      risk: cp.risk?.level ?? null,
      wind: cp.weather.wind_mph,
      gust: cp.weather.gust_mph,
      rain: cp.weather.rain_in_hr,
      snow: cp.weather.snow_in_hr,
      drivers: cp.risk?.drivers ?? [],
      loadRule: cp.risk?.load_rule ?? null,
    }
  }
  const risk = fc.risk[hour]
  return {
    mode: 'snapshot',
    time: forecast.hours[hour],
    status: risk == null ? 'unavailable' : 'ok',
    available: risk != null,
    risk,
    wind: fc.wind[hour],
    gust: null,
    rain: fc.rain[hour],
    snow: fc.snow[hour],
    drivers: [],
    loadRule: null,
  }
}

/** Per-sample risk values for the heatmap at the current mode. */
export function heatValues(forecast, hour) {
  if (!forecast) return []
  return forecast.heat.map((p) => (hour == null ? p.eta_risk : p.risk[hour]))
}

/** Worst risk seen anywhere along the corridor in each forecast hour (null = no data). */
export function maxRiskByHour(forecast) {
  if (!forecast) return []
  return forecast.hours.map((_, h) => {
    let max = null
    for (const p of forecast.heat) {
      const r = p.risk[h]
      if (r != null && (max == null || r > max)) max = r
    }
    return max
  })
}

/** Count of checkpoints per risk level (index 0-4) plus unavailable. */
export function riskCounts(views) {
  const counts = { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0, unavailable: 0 }
  for (const v of views) {
    if (v.risk == null) counts.unavailable += 1
    else counts[v.risk] += 1
  }
  return counts
}
