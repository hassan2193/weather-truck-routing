import { describe, expect, it } from 'vitest'
import { buildField, evaluateField, milesToPixels } from './heatField'
import { decodePolyline } from './polyline'
import { rampRgb, riskMeta } from './risk'
import { validateTrip } from './validation'

describe('decodePolyline', () => {
  it('decodes the documented Google example', () => {
    const pts = decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@', 5)
    expect(pts).toHaveLength(3)
    expect(pts[0][0]).toBeCloseTo(38.5, 5)
    expect(pts[0][1]).toBeCloseTo(-120.2, 5)
    expect(pts[2][0]).toBeCloseTo(43.252, 5)
    expect(pts[2][1]).toBeCloseTo(-126.453, 5)
  })
})

describe('risk palette', () => {
  it('maps levels to the required colours', () => {
    expect(riskMeta(0).color).toBe('#22c55e') // green
    expect(riskMeta(1).color).toBe('#facc15') // yellow
    expect(riskMeta(2).color).toBe('#f97316') // orange
    expect(riskMeta(3).color).toBe('#ef4444') // red
    expect(riskMeta(4).label).toBe('No Travel')
    expect(riskMeta(null).label).toBe('Unavailable')
  })
  it('interpolates the ramp and clamps', () => {
    expect(rampRgb(0)).toEqual([0x22, 0xc5, 0x5e])
    expect(rampRgb(4)).toEqual([0x7f, 0x1d, 0x1d])
    expect(rampRgb(9)).toEqual(rampRgb(4))
    const mid = rampRgb(0.5)
    expect(mid[0]).toBeGreaterThan(0x22)
    expect(mid[0]).toBeLessThan(0xfa)
  })
})

describe('heat field', () => {
  const opts = { width: 200, height: 100, step: 10, radius: 30 }
  it('only covers cells within the radius of a sample', () => {
    const field = buildField([{ x: 100, y: 50 }], opts)
    const cells = evaluateField(field, [2])
    expect(cells.length).toBeGreaterThan(0)
    for (const c of cells) {
      expect(Math.hypot(c.x - 100, c.y - 50)).toBeLessThanOrEqual(30 + 1e-9)
      expect(c.value).toBe(2)
    }
  })
  it('blends neighbouring samples by distance and keeps values in range', () => {
    const field = buildField([{ x: 60, y: 50 }, { x: 140, y: 50 }], opts)
    const cells = evaluateField(field, [0, 4])
    const near = (x) => cells.reduce((a, c) => (Math.abs(c.x - x) < Math.abs(a.x - x) ? c : a))
    expect(near(60).value).toBeLessThan(near(140).value)
    expect(cells.every((c) => c.value >= 0 && c.value <= 4)).toBe(true)
  })
  it('skips samples without data instead of treating them as zero', () => {
    const field = buildField([{ x: 100, y: 50 }], opts)
    expect(evaluateField(field, [null])).toEqual([])
    const two = buildField([{ x: 90, y: 50 }, { x: 110, y: 50 }], opts)
    const cells = evaluateField(two, [3, null])
    expect(cells.every((c) => c.value === 3)).toBe(true)
  })
  it('fades toward the edge of the corridor', () => {
    const cells = evaluateField(buildField([{ x: 100, y: 50 }], opts), [1])
    const centre = cells.find((c) => Math.hypot(c.x - 105, c.y - 55) < 8)
    const edge = cells.reduce((a, c) => (Math.hypot(c.x - 100, c.y - 50) > Math.hypot(a.x - 100, a.y - 50) ? c : a))
    expect(centre.alpha).toBe(1)
    expect(edge.alpha).toBeLessThan(0.5)
  })
  it('converts miles to pixels by zoom', () => {
    const z6 = milesToPixels(15, 40, 6)
    expect(milesToPixels(15, 40, 7)).toBeCloseTo(z6 * 2, 6)
    expect(z6).toBeGreaterThan(5)
  })
})

describe('validateTrip', () => {
  const now = new Date('2026-12-01T12:00:00Z')
  const base = {
    origin: { text: 'Chicago, IL' },
    destination: { text: 'Dallas, TX' },
    departure: '2026-12-02T08:00:00Z',
    loadLb: '42000',
    interval: 25,
  }
  it('accepts a valid trip', () => {
    expect(validateTrip(base, now)).toEqual({})
  })
  it('flags every invalid field', () => {
    const errs = validateTrip(
      { origin: { text: '' }, destination: { text: ' ' }, departure: '', loadLb: '-5', interval: 15 },
      now,
    )
    expect(Object.keys(errs).sort()).toEqual(['departure', 'destination', 'interval', 'loadLb', 'origin'])
  })
  it('rejects past, too-far-future departures and out-of-range loads', () => {
    expect(validateTrip({ ...base, departure: '2026-11-30T00:00:00Z' }, now).departure).toMatch(/past/)
    expect(validateTrip({ ...base, departure: '2027-02-01T00:00:00Z' }, now).departure).toMatch(/16 days/)
    expect(validateTrip({ ...base, loadLb: '500000' }, now).loadLb).toMatch(/exceed/)
    expect(validateTrip({ ...base, loadLb: '10.5' }, now).loadLb).toMatch(/whole/)
    expect(validateTrip({ ...base, loadLb: '0' }, now).loadLb).toBeUndefined()
  })
  it('rejects identical origin and destination', () => {
    expect(validateTrip({ ...base, destination: { text: 'chicago, il' } }, now).destination).toMatch(/differ/)
  })
})
