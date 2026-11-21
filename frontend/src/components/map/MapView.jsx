import L from 'leaflet'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  CircleMarker, LayerGroup, LayersControl, MapContainer, Marker, Polyline, TileLayer, Tooltip, ZoomControl, useMap,
} from 'react-leaflet'
import { Crosshair, Loader2, MapPinned } from 'lucide-react'
import { formatDateTime, formatDuration, formatMiles } from '../../lib/format'
import { ROUTE_COLORS, UNAVAILABLE, riskMeta } from '../../lib/risk'
import { checkpointView, heatValues } from '../../lib/views'
import CheckpointDetails from '../CheckpointDetails'
import HeatCanvasLayer from './HeatCanvasLayer'
import Legend from './Legend'

const US_CENTER = [39.5, -98.35]

const pinIcon = (color, glyph) =>
  L.divIcon({
    className: '',
    html: `<div class="endpoint-pin" style="background:${color}">${glyph}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
const ORIGIN_ICON = pinIcon('#16a34a', '▶')
const DEST_ICON = pinIcon('#0f172a', '⚑')

function HeatLayer({ forecast, hour, visible }) {
  const map = useMap()
  const layer = useRef(null)
  useEffect(() => {
    const l = new HeatCanvasLayer()
    l.addTo(map)
    layer.current = l
    return () => {
      l.remove()
      layer.current = null
    }
  }, [map])
  useEffect(() => {
    layer.current?.setPoints(visible && forecast ? forecast.heat : [])
  }, [forecast, visible])
  useEffect(() => {
    layer.current?.setValues(visible && forecast ? heatValues(forecast, hour) : [])
  }, [forecast, hour, visible])
  return null
}

/**
 * Leaflet popup for the selected checkpoint. Managed imperatively so that only a close
 * initiated by the user (X button / map click) clears the selection; closes caused by our own
 * cleanup (re-renders, StrictMode double-mount) are ignored.
 */
function CheckpointPopup({ position, onClose, children }) {
  const map = useMap()
  const [node] = useState(() => document.createElement('div'))
  const popup = useRef(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    let disposed = false
    const p = L.popup({ offset: [0, -6], maxWidth: 300, minWidth: 250, autoPanPadding: [40, 40] })
    p.setContent(node)
    popup.current = p
    p.on('remove', () => {
      if (!disposed) onCloseRef.current?.()
    })
    return () => {
      disposed = true
      p.remove()
      popup.current = null
    }
  }, [map, node])

  useEffect(() => {
    const p = popup.current
    if (!p) return
    p.setLatLng(position)
    if (!map.hasLayer(p)) p.openOn(map)
    else p.update()
  })

  return createPortal(children, node)
}

function FitBounds({ bounds, signal }) {
  const map = useMap()
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [40, 40], animate: true })
    // refit only when a new analysis arrives
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal])
  return null
}

/** One checkpoint dot. Memoised so scrubbing the slider only repaints dots whose colour changed. */
const CheckpointDot = memo(function CheckpointDot({ cp, color, emphasised, selected, onClick }) {
  return (
    <CircleMarker
      center={[cp.lat, cp.lon]}
      radius={selected ? 10 : emphasised ? 7 : 4.5}
      pathOptions={{
        fillColor: color,
        fillOpacity: emphasised ? 0.95 : 0.7,
        bubblingMouseEvents: false,
        color: selected ? '#0f172a' : '#ffffff',
        weight: selected ? 3 : emphasised ? 2 : 1,
      }}
      eventHandlers={{ click: onClick }}
    />
  )
})

export default function MapView({
  analysis,
  routes,
  selectedRouteId,
  onSelectRoute,
  forecasts,
  hour,
  showHeat,
  selectedCheckpoint,
  onSelectCheckpoint,
  loading,
}) {
  const [map, setMap] = useState(null)
  const geometries = useMemo(() => Object.fromEntries(routes.map((r) => [r.id, r.points])), [routes])
  const bounds = useMemo(() => {
    const all = routes.flatMap((r) => r.points)
    return all.length ? L.latLngBounds(all) : null
  }, [routes])

  const selectedRoute = routes.find((r) => r.id === selectedRouteId) ?? null
  const selectedForecast = selectedRoute ? forecasts[selectedRoute.id]?.data ?? null : null

  // Draw the selected route last so it sits on top of the others.
  const drawOrder = useMemo(
    () => [...routes].sort((a, b) => (a.id === selectedRouteId) - (b.id === selectedRouteId)),
    [routes, selectedRouteId],
  )

  const handleDotClick = useCallback(
    (routeId, sequence) => () => {
      onSelectRoute(routeId)
      onSelectCheckpoint({ routeId, sequence })
    },
    [onSelectRoute, onSelectCheckpoint],
  )

  const popupRoute = selectedCheckpoint ? routes.find((r) => r.id === selectedCheckpoint.routeId) : null
  const popupCp = popupRoute?.checkpoints.find((c) => c.sequence === selectedCheckpoint.sequence)

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl">
      <MapContainer
        ref={setMap}
        center={US_CENTER}
        zoom={4}
        minZoom={3}
        zoomControl={false}
        preferCanvas
        className="h-full w-full"
        worldCopyJump
      >
        <LayersControl position="topleft" collapsed>
          <LayersControl.BaseLayer checked name="Light map">
            <LayerGroup>
              <TileLayer
                attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
                url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
                maxNativeZoom={16}
                maxZoom={19}
              />
              <TileLayer
                url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
                maxNativeZoom={16}
                maxZoom={19}
              />
            </LayerGroup>
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Streets">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />
          </LayersControl.BaseLayer>
        </LayersControl>
        <ZoomControl position="topright" />
        <HeatLayer forecast={selectedForecast} hour={hour} visible={showHeat} />
        {bounds && <FitBounds bounds={bounds} signal={analysis?.id} />}

        {selectedRoute && (
          // white casing under the selected route so it stands out from the others
          <Polyline
            key={`${selectedRoute.id}-casing`}
            positions={geometries[selectedRoute.id]}
            smoothFactor={1.5}
            pathOptions={{ color: '#ffffff', weight: 11, opacity: 0.95, lineCap: 'round', lineJoin: 'round' }}
            interactive={false}
          />
        )}
        {drawOrder.map((route) => {
          const selected = route.id === selectedRouteId
          const color = ROUTE_COLORS[route.index % ROUTE_COLORS.length]
          return (
            <Polyline
              key={`${route.id}-main`}
              positions={geometries[route.id]}
              smoothFactor={1.5}
              pathOptions={{
                color,
                weight: selected ? 6 : 4,
                opacity: selected ? 1 : 0.6,
                lineCap: 'round',
                lineJoin: 'round',
                bubblingMouseEvents: false,
              }}
              eventHandlers={{ click: () => onSelectRoute(route.id) }}
            >
              <Tooltip sticky direction="top">
                <strong>Route {route.label}</strong>
                {route.is_recommended ? ' · Recommended' : ''}
                <br />
                {route.summary}
                <br />
                {formatMiles(route.distance_mi)} · {formatDuration(route.duration_s)} · arrives {formatDateTime(route.arrival_time)}
              </Tooltip>
            </Polyline>
          )
        })}

        {drawOrder.flatMap((route) => {
          const selected = route.id === selectedRouteId
          const forecast = forecasts[route.id]?.data
          return route.checkpoints.map((cp) => {
            const view = checkpointView(cp, forecast, hour)
            const color = view.available ? riskMeta(view.risk).color : UNAVAILABLE.color
            const isSel = selectedCheckpoint?.routeId === route.id && selectedCheckpoint?.sequence === cp.sequence
            return (
              <CheckpointDot
                key={`${route.id}-${cp.sequence}`}
                cp={cp}
                color={color}
                emphasised={selected}
                selected={isSel}
                onClick={handleDotClick(route.id, cp.sequence)}
              />
            )
          })
        })}

        {analysis && (
          <>
            <Marker position={[analysis.origin.lat, analysis.origin.lon]} icon={ORIGIN_ICON}>
              <Tooltip direction="top" offset={[0, -12]}>
                Start: {analysis.origin.label}
              </Tooltip>
            </Marker>
            <Marker position={[analysis.destination.lat, analysis.destination.lon]} icon={DEST_ICON}>
              <Tooltip direction="top" offset={[0, -12]}>
                Destination: {analysis.destination.label}
              </Tooltip>
            </Marker>
          </>
        )}

        {popupCp && (
          <CheckpointPopup position={[popupCp.lat, popupCp.lon]} onClose={() => onSelectCheckpoint(null)}>
            <CheckpointDetails
              route={popupRoute}
              checkpoint={popupCp}
              view={checkpointView(popupCp, forecasts[popupRoute.id]?.data, hour)}
            />
          </CheckpointPopup>
        )}
      </MapContainer>

      {bounds && (
        <button
          type="button"
          onClick={() => map?.fitBounds(bounds, { padding: [40, 40] })}
          className="absolute top-[84px] right-[10px] z-[1000] grid h-[34px] w-[34px] place-items-center rounded-sm border-2 border-black/20 bg-white text-slate-700 shadow-sm hover:bg-slate-50"
          title="Fit all routes"
          aria-label="Fit all routes in view"
        >
          <Crosshair size={16} />
        </button>
      )}

      <Legend showHeat={showHeat} />

      {!analysis && !loading && (
        <div className="pointer-events-none absolute inset-0 z-[900] grid place-items-center p-6">
          <div className="max-w-xs rounded-xl bg-white/90 p-5 text-center shadow-lg backdrop-blur">
            <MapPinned className="mx-auto mb-2 text-brand-500" />
            <p className="text-sm font-semibold text-slate-800">Plan a trip to see routes and weather</p>
            <p className="mt-1 text-xs text-slate-500">
              Three truck routes, forecast risk at every checkpoint, and a 48-hour weather heatmap will appear here.
            </p>
          </div>
        </div>
      )}
      {loading && (
        <div className="absolute inset-0 z-[1100] grid place-items-center bg-white/55 backdrop-blur-[1px]">
          <div className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-lg">
            <Loader2 className="animate-spin text-brand-500" size={16} /> Analysing routes and weather…
          </div>
        </div>
      )}
    </div>
  )
}
