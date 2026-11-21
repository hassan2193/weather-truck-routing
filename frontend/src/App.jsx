import { useCallback, useMemo, useState } from 'react'
import CheckpointTable from './components/CheckpointTable'
import ForecastPanel from './components/ForecastPanel'
import Header from './components/Header'
import MapView from './components/map/MapView'
import MethodologyModal from './components/MethodologyModal'
import RecommendationCard from './components/RecommendationCard'
import RouteCard from './components/RouteCard'
import TripForm from './components/TripForm'
import { EmptyResults, ErrorBanner, ResultsSkeleton, WarningList } from './components/ui'
import { useAnalysis } from './hooks/useAnalysis'
import { useForecasts } from './hooks/useForecast'
import { useHealth } from './hooks/useHealth'
import { decodePolyline } from './lib/polyline'
import { checkpointView } from './lib/views'

export default function App() {
  const health = useHealth()
  const analysis = useAnalysis()
  const runAnalysis = analysis.run
  const [lastPayload, setLastPayload] = useState(null)
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const [selectedCheckpoint, setSelectedCheckpoint] = useState(null)
  const [hour, setHour] = useState(null) // null = trip view (weather at ETA); 0-48 = forecast snapshot
  const [showHeat, setShowHeat] = useState(true)
  const [methodologyOpen, setMethodologyOpen] = useState(false)

  const data = analysis.data
  const loading = analysis.status === 'loading'

  // Decode route geometry once per analysis.
  const routes = useMemo(
    () => (data ? data.routes.map((r) => ({ ...r, points: decodePolyline(r.geometry, r.geometry_precision) })) : []),
    [data],
  )
  const selectedRoute = routes.find((r) => r.id === selectedRouteId) ?? null

  const forecasts = useForecasts(
    useMemo(() => routes.map((r) => r.id), [routes]),
    selectedRouteId,
  )
  const selectedForecast = selectedRoute ? forecasts[selectedRoute.id]?.data ?? null : null

  const views = useMemo(
    () => (selectedRoute ? selectedRoute.checkpoints.map((cp) => checkpointView(cp, selectedForecast, hour)) : []),
    [selectedRoute, selectedForecast, hour],
  )

  const submit = useCallback(
    async (payload) => {
      setLastPayload(payload)
      const result = await runAnalysis(payload)
      if (result) {
        // Start from the recommended route with a clean selection for every new analysis.
        setSelectedRouteId(result.recommendation.route_id)
        setSelectedCheckpoint(null)
        setHour(null)
      }
    },
    [runAnalysis],
  )

  const serverFieldErrors = useMemo(() => {
    const details = analysis.error?.details
    if (analysis.error?.code !== 'validation_error' || !details) return {}
    return Object.fromEntries(Object.entries(details).map(([k, v]) => [k, Array.isArray(v) ? v.join(' ') : String(v)]))
  }, [analysis.error])

  return (
    <div className="min-h-screen">
      <Header health={health} onOpenMethodology={() => setMethodologyOpen(true)} weatherStats={data?.weather_stats} />
      <MethodologyModal open={methodologyOpen} onClose={() => setMethodologyOpen(false)} />

      <main id="planner" className="mx-auto grid max-w-[1800px] gap-4 p-3 sm:p-4 lg:grid-cols-[minmax(340px,420px)_1fr]">
        {/* ---- left column: input + results ---- */}
        <div className="space-y-4">
          <TripForm onSubmit={submit} loading={loading} serverErrors={serverFieldErrors} />

          {analysis.status === 'error' && analysis.error?.code !== 'validation_error' && (
            <ErrorBanner
              error={analysis.error}
              title="We couldn’t analyse that trip"
              onRetry={lastPayload ? () => submit(lastPayload) : undefined}
            />
          )}

          {loading && <ResultsSkeleton />}

          {!loading && data && (
            <>
              <RecommendationCard analysis={data} />
              <WarningList warnings={data.warnings} />
              {data.route_search?.message && routes.length >= 3 && (
                <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200">
                  {data.route_search.message}
                </p>
              )}
              <div className="space-y-3" role="list" aria-label="Route options">
                {routes.map((r) => (
                  <div role="listitem" key={r.id}>
                    <RouteCard
                      route={r}
                      selected={r.id === selectedRouteId}
                      onSelect={() => {
                        setSelectedRouteId(r.id)
                        setSelectedCheckpoint(null)
                      }}
                    />
                  </div>
                ))}
              </div>
            </>
          )}

          {!loading && !data && analysis.status !== 'error' && <EmptyResults />}
        </div>

        {/* ---- right column: map, forecast slider, checkpoints ---- */}
        <div className="min-w-0 space-y-4">
          <div className="h-[clamp(380px,58vh,680px)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <MapView
              analysis={data}
              routes={routes}
              selectedRouteId={selectedRouteId}
              onSelectRoute={setSelectedRouteId}
              forecasts={forecasts}
              hour={hour}
              showHeat={showHeat}
              selectedCheckpoint={selectedCheckpoint}
              onSelectCheckpoint={setSelectedCheckpoint}
              loading={loading}
            />
          </div>

          {selectedRoute && !loading && (
            <>
              <ForecastPanel
                forecast={selectedForecast}
                loading={forecasts[selectedRoute.id]?.loading}
                error={forecasts[selectedRoute.id]?.error}
                hour={hour}
                onHourChange={setHour}
                showHeat={showHeat}
                onToggleHeat={setShowHeat}
                views={views}
              />
              <CheckpointTable
                route={selectedRoute}
                views={views}
                snapshot={hour != null}
                selectedSequence={selectedCheckpoint?.routeId === selectedRoute.id ? selectedCheckpoint.sequence : null}
                onSelect={(sequence) => setSelectedCheckpoint({ routeId: selectedRoute.id, sequence })}
              />
            </>
          )}
        </div>
      </main>

      <footer className="mx-auto max-w-[1800px] px-4 pb-6 text-center text-[11px] text-slate-400">
        Routing by Valhalla · Weather by Open-Meteo · Map tiles © Esri / OpenStreetMap contributors. Forecasts are estimates; always
        follow dispatch and local road advisories.
      </footer>
    </div>
  )
}
