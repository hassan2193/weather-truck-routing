// Interpolation behind the weather heatmap (pure functions, no DOM).
//
// Each sample point carries a real risk value from the forecast. A cell near the
// route gets the Gaussian-weighted average of the values of sample points within
// `radius` pixels, and fades out toward the edge of that radius. Nothing is drawn
// where there is no sample nearby, so the heatmap never invents weather far from
// the route. Geometry is built once per map view; changing the forecast hour only
// re-evaluates the (cheap) weighted averages.

const smoothstep = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/**
 * @param {{x:number,y:number}[]} points   sample positions in canvas pixels
 * @param {{width:number,height:number,step:number,radius:number}} opts
 */
export function buildField(points, { width, height, step, radius }) {
  const cells = new Map()
  const r2 = radius * radius
  points.forEach((p, pi) => {
    const minCx = Math.max(0, Math.floor((p.x - radius) / step))
    const maxCx = Math.min(Math.floor(width / step), Math.floor((p.x + radius) / step))
    const minCy = Math.max(0, Math.floor((p.y - radius) / step))
    const maxCy = Math.min(Math.floor(height / step), Math.floor((p.y + radius) / step))
    for (let cy = minCy; cy <= maxCy; cy += 1) {
      for (let cx = minCx; cx <= maxCx; cx += 1) {
        const x = cx * step + step / 2
        const y = cy * step + step / 2
        const d2 = (x - p.x) ** 2 + (y - p.y) ** 2
        if (d2 > r2) continue
        const key = cy * 100000 + cx
        let cell = cells.get(key)
        if (!cell) {
          cell = { x, y, idx: [], w: [], dmin2: Infinity }
          cells.set(key, cell)
        }
        cell.idx.push(pi)
        cell.w.push(Math.exp((-3 * d2) / r2))
        if (d2 < cell.dmin2) cell.dmin2 = d2
      }
    }
  })
  const list = [...cells.values()].map((c) => ({
    x: c.x,
    y: c.y,
    idx: Int32Array.from(c.idx),
    w: Float32Array.from(c.w),
    fade: 1 - smoothstep(0.55 * radius, radius, Math.sqrt(c.dmin2)),
  }))
  return { cells: list, step, radius }
}

/**
 * Evaluate the field for the given per-point values (number in [0,4] or null).
 * Returns an array of {x, y, value, alpha} for cells that have at least one valid sample.
 */
export function evaluateField(field, values) {
  const out = []
  for (const cell of field.cells) {
    let wsum = 0
    let vsum = 0
    for (let k = 0; k < cell.idx.length; k += 1) {
      const v = values[cell.idx[k]]
      if (v == null) continue
      wsum += cell.w[k]
      vsum += cell.w[k] * v
    }
    if (wsum === 0) continue
    out.push({ x: cell.x, y: cell.y, value: vsum / wsum, alpha: cell.fade })
  }
  return out
}

/** Pixel radius for a corridor of `miles` at a given latitude and zoom (Web Mercator). */
export function milesToPixels(miles, lat, zoom) {
  const metersPerPixel = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom
  return (miles * 1609.344) / metersPerPixel
}
