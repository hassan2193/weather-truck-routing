import L from 'leaflet'
import { buildField, evaluateField, milesToPixels } from '../../lib/heatField'
import { rampRgb } from '../../lib/risk'

const CELL_PX = 9
const CORRIDOR_MILES = 14
const MIN_RADIUS_PX = 16

/**
 * Canvas overlay that paints interpolated weather risk along the trip corridor.
 *
 * Sample positions come from the forecast API (real data). Geometry (which
 * pixels are near which sample) is rebuilt only when the map view changes;
 * moving the forecast slider only calls `setValues`, which re-evaluates the
 * weighted averages and repaints, so scrubbing stays smooth.
 */
export default class HeatCanvasLayer extends L.Layer {
  constructor(options = {}) {
    super()
    L.setOptions(this, { pane: 'heat', ...options })
    this._latlngs = []
    this._values = []
    this._field = null
  }

  onAdd(map) {
    this._map = map
    if (!map.getPane(this.options.pane)) {
      const pane = map.createPane(this.options.pane)
      pane.style.zIndex = 350
      pane.style.pointerEvents = 'none'
    }
    this._canvas = L.DomUtil.create('canvas', 'heat-canvas leaflet-zoom-animated')
    map.getPane(this.options.pane).appendChild(this._canvas)
    this._reset()
  }

  onRemove() {
    this._canvas.remove()
    this._canvas = null
  }

  getEvents() {
    const events = { moveend: this._reset, resize: this._reset }
    if (this._map?._zoomAnimated) events.zoomanim = this._animateZoom
    return events
  }

  /** Replace the sample locations: [{lat, lon}, ...]. */
  setPoints(points) {
    this._latlngs = points.map((p) => L.latLng(p.lat, p.lon))
    if (this._map) this._reset()
  }

  /** Set the risk value (0-4 or null) for each sample, in the same order as setPoints. */
  setValues(values) {
    this._values = values
    if (this._map) this._draw()
  }

  _reset() {
    const map = this._map
    if (!map || !this._canvas) return
    const size = map.getSize()
    const topLeft = map.containerPointToLayerPoint([0, 0])
    L.DomUtil.setPosition(this._canvas, topLeft)
    this._canvas.width = size.x
    this._canvas.height = size.y
    this._canvas.style.width = `${size.x}px`
    this._canvas.style.height = `${size.y}px`
    L.DomUtil.setTransform(this._canvas, topLeft, 1)

    if (!this._latlngs.length) {
      this._field = null
    } else {
      const midLat = this._latlngs[Math.floor(this._latlngs.length / 2)].lat
      const radius = Math.max(MIN_RADIUS_PX, milesToPixels(CORRIDOR_MILES, midLat, map.getZoom()))
      const pts = this._latlngs.map((ll) => map.latLngToContainerPoint(ll))
      this._field = buildField(pts, { width: size.x, height: size.y, step: CELL_PX, radius })
    }
    this._draw()
  }

  _draw() {
    const canvas = this._canvas
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!this._field) return
    const half = CELL_PX / 2 + 1
    for (const cell of evaluateField(this._field, this._values)) {
      const [r, g, b] = rampRgb(cell.value)
      // higher risk paints more opaque so dangerous stretches stand out from calm ones
      const alpha = cell.alpha * (0.55 + 0.45 * Math.min(1, cell.value / 3))
      ctx.fillStyle = `rgba(${r | 0},${g | 0},${b | 0},${alpha.toFixed(3)})`
      ctx.fillRect(cell.x - half, cell.y - half, half * 2, half * 2)
    }
  }

  _animateZoom(e) {
    const map = this._map
    const scale = map.getZoomScale(e.zoom)
    const offset = map._latLngBoundsToNewLayerBounds(map.getBounds(), e.zoom, e.center).min
    L.DomUtil.setTransform(this._canvas, offset, scale)
  }
}
