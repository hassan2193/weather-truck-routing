# HaulWise — Weather-Aware Truck Routing

A React + Django app that helps a truck driver choose the safest route. Given an origin, destination, departure time and load weight it:

1. generates up to **three truck routes** (Valhalla, `costing=truck`),
2. samples **weather every 10 / 25 / 50 miles at the truck's estimated arrival time** at each checkpoint (Open-Meteo),
3. classifies each checkpoint with the assessment's **wind / rain / snow thresholds and load rules**,
4. **recommends** a route using the required priority order (severe miles → high miles → average risk → travel time),
5. shows everything on an interactive map, with a **weather heatmap and a 0–48 h forecast slider**.

> Stack: React 19 + Vite + Tailwind CSS 4 + React-Leaflet + Lucide · Django 5 + Django REST Framework · PostgreSQL.
> No third-party API keys are required for the default providers.

---

## Contents

- [Quick start](#quick-start) · [Tests](#tests) · [Configuration](#configuration)
- [How it works](#how-it-works) — [providers](#provider-choices-and-what-was-verified) · [risk rules](#risk-rules-and-boundary-interpretation) · [checkpoints & ETA](#checkpoints-and-eta) · [weather & caching](#weather-sampling-and-caching) · [recommendation](#route-recommendation) · [heatmap](#heatmap-and-forecast-slider)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)
- [Loom walkthrough outline](#loom-walkthrough-outline-510-min)

---

## Quick start

Prerequisites: Python, Node and PostgreSQL (or Docker for the database). Everything here was developed and tested with **Python 3.13, Node 24 and PostgreSQL 16.9** on Windows 11; the Docker image targets Python 3.12 / Node 22 (see [Deployment](#deployment) for what has and has not been verified).

> **On Windows?** Jump to [Running on Windows](#running-on-windows-powershell); the bash commands below use `cp` and `source`.

### 1. Database

```bash
# easiest: only the DB from docker-compose (Docker Desktop must be running)
docker compose up -d db
# → postgres://haulwise:haulwise@localhost:5432/haulwise
```

Any PostgreSQL works; just set `DATABASE_URL` accordingly. If `DATABASE_URL` is unset the backend falls back to a local SQLite file, which exists only so the unit tests run with zero setup.

### 2. Backend (Django, port 8000)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then edit if needed (DATABASE_URL etc.)
python manage.py migrate
python manage.py runserver 8000
```

### 3. Frontend (Vite, port 5173)

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173  (proxies /api → :8000)
```

Open <http://localhost:5173>, enter a trip (e.g. *Chicago, IL → Dallas, TX*) and press **Find safest route**.

### Running on Windows (PowerShell)

Open **two** PowerShell windows at the repo root. Calling the venv's `python` directly avoids execution-policy problems with `Activate.ps1`.

```powershell
# --- one-time: database (Docker Desktop must be running) ---
docker compose up -d db
#   No Docker? Skip this and delete the DATABASE_URL line from backend\.env (step below);
#   the backend then uses a local SQLite file. Fine for trying the app, not for production.

# --- window 1: backend (http://localhost:8000) ---
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver 8000

# --- window 2: frontend (http://localhost:5173) ---
cd frontend
npm install
npm run dev
```

Then open <http://localhost:5173>. Run the tests with `.\.venv\Scripts\python -m pytest` (in `backend`) and `npm test` (in `frontend`). `gunicorn` does not run on Windows; it is only used inside the Docker image.

### One-command production-like run

```bash
docker compose up --build            # http://localhost:8000 (API + built React app + Postgres)
```

---

## Tests

```bash
# backend: 187 tests (risk boundaries, checkpoints, ETA, weather sampling/caching, ranking, API errors…)
cd backend && pytest

# opt-in: hits the real Valhalla / Open-Meteo / Photon services
RUN_LIVE_TESTS=1 pytest tests/test_live.py

# frontend: polyline decoding, heat-field interpolation, validation, palette
cd frontend && npm test

# static checks
cd backend && ruff check .
cd frontend && npm run lint && npm run build
```

What is covered (backend):

| Area | Tests |
|---|---|
| Wind / rain / snow thresholds | every boundary incl. 24.9/25, 34.9/35, 44.9/45, 54.9/55 mph; 0.0999/0.10, 0.25, 0.50, 1.00/1.001 in/hr; 0.5, 1.0, 2.0, 3.0/3.001 in/hr |
| Load rules | 30,000 / 30,001 lb and 40,000 / 40,001 lb against 35, 44, 45, 54, 55 mph |
| Checkpoint generation | 10/25/50 mi spacing, origin + destination included, segments tile the route exactly, points lie on a *bent* route (not the chord), rescaling to provider distance |
| ETA | constant-speed and per-segment speed profiles, monotonicity, clamping |
| Weather sampling | arrival-time (not departure-time) lookup, beyond-horizon / before-start / missing data statuses, dedupe, batching, cache hit/refetch, outage handling |
| Three-route search | direct 3 / 2 / 1 routes, near-duplicate & minor-coordinate detection, parallel-road tolerance, short-detour rejection, diversified re-routing (request carries `exclude_polygons`, stays under the 10 km limit, avoids endpoints), excessive-detour rejection, provider failure / no-path during re-routing, time budget, No Travel rules on re-routed routes, user-facing explanations |
| Risk miles & ranking | miles use segment length (not checkpoint count), lexicographic order, No-Travel gate, float-noise tolerance, missing-weather handling, explanations |
| API | full pipeline with the HTTP layer mocked (`responses`): validation errors, no-route (422), provider down (502), weather outage (graceful), < 3 routes, beyond forecast horizon, 404s, forecast payload |

The unit/API tests mock only the *network*; the pipeline, database and serializers run for real. `tests/test_live.py` exercises the real providers end-to-end.

---

## Configuration

All configuration is by environment variable — see [`backend/.env.example`](backend/.env.example) and [`frontend/.env.example`](frontend/.env.example). Highlights:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django basics (secret key is *required* when debug is off) |
| `CORS_ALLOWED_ORIGINS` | only if the frontend is on a different origin than the API |
| `VALHALLA_URL` / `VALHALLA_API_KEY` | routing provider (defaults to the public FOSSGIS instance) |
| `OPEN_METEO_URL` / `OPEN_METEO_API_KEY` | weather provider (defaults to the free endpoint) |
| `PHOTON_URL`, `NOMINATIM_URL`, `HTTP_USER_AGENT` | geocoding; set the User-Agent to identify your deployment |
| `TRUCK_TARE_LB` | assumed empty weight of tractor+trailer added to the load for road weight restrictions |
| `WEATHER_CACHE_TTL_SECONDS`, `WEATHER_GRID_DEGREES`, `WEATHER_BATCH_SIZE` | weather caching/batching |

---

## How it works

```
React (Vite) ──► POST /api/routes/analyze/ ──► routing.services.analyze_trip
                                                   │ 1 valhalla.fetch_routes      (≤3 truck routes, geometry, per-maneuver times)
                                                   │ 2 checkpoints.generate…      (points on the real geometry, ETA profile)
                                                   │ 3 weather.service.get_series (dedupe → cache → batched Open-Meteo calls)
                                                   │ 4 weather.series.sample…     (value at each checkpoint's ETA)
                                                   │ 5 risk_engine.assess         (wind/rain/snow + load rules)
                                                   │ 6 recommendations.*          (risk miles → rank → explanation)
                                                   ▼
                                              PostgreSQL (Analysis → Route → Checkpoint)
```

The Django code is split along the lines requested in the brief, with business logic kept out of the views:

| App | Responsibility |
|---|---|
| `risk_engine` | pure functions: thresholds, load rules, `assess()` |
| `weather` | Open-Meteo client, hourly series, sampling at a time, de-duplicating/caching service |
| `routing` | Valhalla + geocoding clients, geometry, checkpoints/ETA, **pipeline** (`services.py`), forecast builder, models |
| `recommendations` | risk-mile metrics, lexicographic ranking, explanation text |
| `api` | DRF serializers, thin views, uniform error format |

### Provider choices and what was verified

I checked each provider's actual behaviour rather than assuming it:

- **Routing — Valhalla (FOSSGIS public instance), `costing: truck`.** Verified live that one request returns the primary route plus two alternates (3 routes) with an encoded polyline and per-maneuver distance/time. OSRM's public server returned only 2 alternatives on the same trip, so it was not used. (OpenRouteService and GraphHopper were not evaluated; both need an API key.) Passing the truck weight (load + tare) lets Valhalla honour weight restrictions. Valhalla's truck mode often suggests fewer than three alternatives, so routes are completed by the [three-route search](#three-distinct-routes) below.
- **Weather — Open-Meteo** hourly forecast. Verified: `wind_speed_10m` in mph, precipitation/snowfall in inches, multiple coordinates per request, up to 16 days ahead. **Rain intensity = `rain` + `showers`** (convective rain is reported separately by Open-Meteo and would otherwise be missed). Snow intensity is `snowfall` (inches of snow depth per hour). Wind is the sustained 10 m speed; gusts are shown for information but not used for classification.
- **Weather fallback — US National Weather Service (weather.gov)**, used only for US checkpoints Open-Meteo cannot serve (e.g. HTTP 429 when a shared hosting IP exhausts the free daily quota). Documented flow `/points/{lat},{lon}` → `/gridpoints/{office}/{x},{y}` with a descriptive User-Agent; grid lookups cached 24 h (including "not covered" 404s), grid data 1 h, one request per grid cell. Wind km/h → mph; precipitation and snowfall (mm per 1–6 h interval) → average in/hr for that interval, so short bursts can be understated; missing values stay unavailable. After an Open-Meteo 429 it is paused for 10 min. Outside the US nothing changes (unavailable). Set `HTTP_USER_AGENT` / `NWS_USER_AGENT` to include a contact.
- **Geocoding — Photon** for autocomplete (built for typeahead) with **Nominatim** as a fallback; results restricted to North America.
- **Map tiles — Esri Light Gray** (plus labels) and OpenStreetMap as an alternate layer; both are keyless. (CARTO's free tiles now require a key, so they were not used.)

### Risk rules and boundary interpretation

The PDF's ranges (`25–34`, `0.10–0.25`, …) leave gaps for fractional values and share endpoints between rain/snow bands. The rules implemented in [`backend/risk_engine/rules.py`](backend/risk_engine/rules.py) are deterministic and applied identically to wind, rain and snow:

* every band is **lower-bound inclusive, upper-bound exclusive** — `[lo, hi)`. 35 mph is **High**; 0.25 in/hr rain is **High**; 0.5 in/hr snow is **Moderate**; 34.9 mph is **Moderate**;
* where No Travel is written with a strict "`>`" (rain `> 1.00`, snow `> 3.0`) the boundary value itself is **Severe** (those are the closed top of the Severe band). Wind's No Travel is `≥ 55`, so 55 mph is **No Travel**.

| | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | [25, 35) | [35, 45) | [45, 55) | ≥ 55 |
| Rain (in/hr) | < 0.10 | [0.10, 0.25) | [0.25, 0.50) | [0.50, 1.00] | > 1.00 |
| Snow (in/hr) | < 0.5 | [0.5, 1.0) | [1.0, 2.0) | [2.0, 3.0] | > 3.0 |

Load rules (comparisons are strict `>` as written): wind ≥ 55 → No Travel for any load; wind 45–54 and load > 30,000 lb → No Travel; wind 35–44 and load > 40,000 lb → Severe. A checkpoint's level is the **highest** of its wind (after load rules), rain and snow levels. Missing inputs are skipped, never treated as zero; if everything is missing the checkpoint is **unavailable**, not "Low".

### Three distinct routes

Implemented in [`routing/route_search.py`](backend/routing/route_search.py) and [`routing/diversity.py`](backend/routing/diversity.py).

1. **Ask directly.** One Valhalla truck request for the best route plus 2 alternates.
2. **Drop near-duplicates.** A route counts as new only if at least **15% of its length (and ≥ 2 mi)** lies more than **0.5 mi** from *every* route already accepted. This catches identical roads with slightly different coordinates, parallel carriageways and frontage roads, and short local detours. (Real example: Valhalla's "three" Dallas→Fort Worth routes include two that are the same road.)
3. **Re-route around what was found.** If fewer than three remain, ask Valhalla again with small `exclude_polygons` "road blocks" placed at several points along *all* routes found so far (e.g. at 30/50/70% of their length, never within 3 mi of the origin or destination). Valhalla must then find a different corridor. Up to 4 attempts with different block positions, a 30 s timeout each and a 60 s overall budget. Each reply's own alternates are considered too.
4. **Validate every candidate** with the same distinctness test, and reject excessive detours: a re-routed candidate may take at most **1.5×** the fastest route's drive time.
5. Every accepted route (direct or re-routed) is a **real Valhalla truck route** and goes through the full pipeline: its own distance, time profile, checkpoints, ETAs, weather and risk. The recommendation engine and No Travel gate compare all of them equally. Cards mark re-routed ones as **"Alternative corridor"**.

If three distinct routes still can't be found, the app shows what it has and explains why, e.g. *"Only 2 genuinely distinct truck routes could be found for this trip. The routing service suggested 2 distinct truck routes. We made 4 re-routing attempts around sections of the found routes: 5 candidate routes took over 1.5x the fastest drive time; 1 attempt found no path or failed. No routes were invented."*

Measured provider facts behind the design: Valhalla 3.9.3 (public FOSSGIS server) rejects `exclude_polygons` over **10 km total circumference** (error 167), so large avoidance areas are impossible. Blocks are therefore small (≤ 0.4 km radius) and kept within a 9 km budget. `use_highways=0` produced an absurd 413 mi / 8.7 h route for a 240 mi trip, and `shortest=true` a near-identical one (1.9% unique), so neither is used.

**Results on 14 real trips** (live providers, 40,000 lb, run on 2026-11-21):

| Routes | Trips |
|---|---|
| **3** (all direct) | Chicago→Dallas, Los Angeles→Las Vegas, Denver→Salt Lake City, Atlanta→Nashville, Miami→Orlando, San Francisco→Sacramento, Minneapolis→Chicago |
| **3** (with re-routing) | Dallas→Houston (1 direct + 2), Houston→San Antonio (1 + 2), New York→Boston (2 + 1), Kansas City→St. Louis (2 + 1), Dallas→Fort Worth (2 distinct of 3 suggested + 1) |
| **2** | Seattle→Portland (2 direct; re-routed candidates were all > 1.5× drive time), Phoenix→Tucson (1 direct + 1 re-routed at 1.39×; others > 1.5×) |
| **1** | none in this sample |

### Checkpoints and ETA

* Checkpoints are placed at 0, *k*·interval, … and always at the destination, **by walking the actual route geometry** (not a straight line). Vertex distances are rescaled so cumulative distance matches the provider's road distance.
* ETA comes from Valhalla's **per-maneuver length and duration**, giving a piecewise speed profile (slow city streets, fast interstates) instead of one average speed. `ETA = departure + elapsed(distance)`.
* Each checkpoint **represents the stretch of road from the midpoint to its neighbours** (clipped to the route ends). These segments tile the route, so **risk miles are real miles**, independent of the chosen interval.

### Weather sampling and caching

* Weather is read at each checkpoint's **ETA**. Wind (instantaneous) uses the nearest hour; rain/snow (hourly totals that Open-Meteo stamps at the *end* of the hour) use the hour that contains the ETA.
* If an ETA is past the 16-day forecast horizon (or the provider has no data / fails) the checkpoint is **"unavailable"** with a reason, excluded from risk totals, and called out in warnings. It is never filled with made-up values.
* **Efficiency:** coordinates are snapped to a 0.05° grid (finer than the underlying models), so nearby checkpoints and shared highway between alternatives collapse into one location; each unique location is fetched **once as a full hourly series** and reused for ETA sampling, the heatmap and the 48 h slider; series are cached (30 min); cache misses go out in batches of 50 locations, in parallel, with retries. A typical 1,000-mile analysis makes 1–3 weather requests.

### Route recommendation

Routes are ranked by a **strict lexicographic key** — fewest **Severe** miles, then fewest **High** miles, then lowest distance-weighted **average risk** (Low 0 … No Travel 4), then shortest **time** (comparison tolerates only floating-point noise). On top of that, a **safety gate**: a route containing any No Travel segment is never ranked above one without. If *all* routes contain No Travel the least-bad is shown with a prominent "no safe route" warning. Routes without weather data are not rewarded. The response includes a plain-language explanation, e.g.

> *Route B is recommended because it has fewer severe-weather miles (0.0 mi vs 40.0 mi on Route A) and lower overall weather exposure …*

and routes with No Travel list *where and why* (`Miles 140-190: Wind 58 mph → No Travel`).

### Heatmap and forecast slider

`GET /api/routes/{id}/forecast/` returns, for the route's checkpoints and ~120 denser corridor samples, the **hourly wind/rain/snow and the resulting risk level for the 49 hours from departure**, all from Open-Meteo through the same cache (about 30 KB of JSON for a 186-mile trip). Risk is computed server-side with the same engine, so the UI never re-implements the rules.

* The slider moves through hours 0–48 **without any network call**; checkpoints, table, popup and heatmap all update. "Back to trip view" returns to ETA-based weather.
* The heatmap is a custom canvas layer: each cell shows the distance-weighted average of real forecast samples within ~14 mi of the route and fades to nothing beyond that. It does not draw anything where there is no data nearby. Interpolating geometry is built once per map view; scrubbing only re-evaluates the weighted averages, so it stays smooth.
* The strip behind the slider shows the **worst risk along the route in each hour**, so you can spot the dangerous window at a glance.

---

## API reference

All errors share one shape: `{"error": {"code", "message", "details"}}` (`validation_error` 400, `address_not_found`/`no_route`/`invalid_trip` 422, `routing_unavailable`/`weather_unavailable`/`geocoding_unavailable` 502, `not_found` 404).

### `POST /api/routes/analyze/`

```jsonc
{
  "origin": "Chicago, IL",                       // text, or {"label","lat","lon"} from autocomplete
  "destination": {"label": "Dallas, TX", "lat": 32.77, "lon": -96.79},
  "departure_time": "2026-12-01T14:00:00Z",      // ISO 8601 with offset; ≤ 16 days ahead
  "load_weight_lb": 42000,                       // 0 – 120,000
  "interval_miles": 25                           // 10 | 25 | 50
}
```

`201` → analysis with `recommendation` (`route_id`, `headline`, `details[]`, `warnings[]`, `all_routes_unsafe`), `warnings[]`, `weather_stats` (unique locations, cache hits, upstream requests), `route_search` (`found`, `provider_suggested`, `provider_distinct`, `diversified`, `attempts`, `rejected_duplicates`, `rejected_detours`, `failed_attempts`, `message`), and `routes[]`, each with `label`, `source` (`provider` | `diversified`), `distance_mi`, `duration_s`, `arrival_time`, `summary`, `geometry` (encoded polyline, precision 6), `metrics` (`low/moderate/high/severe/no_travel/unknown_miles`, `average_risk`, `weather_coverage`), `rank`, `is_recommended`, `no_travel`, `no_travel_reasons[]` and `checkpoints[]` (`sequence`, `distance_mi`, `segment_mi`, `lat`, `lon`, `eta`, `weather{status,valid_time,wind_mph,gust_mph,rain_in_hr,snow_in_hr}`, `risk{level,label,wind,rain,snow,load_rule,drivers[]}|null`).

### Other endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/routes/{id}/` | one route (metrics + geometry) |
| GET | `/api/routes/{id}/checkpoints/` | its checkpoints in travel order |
| GET | `/api/routes/{id}/forecast/` | 0–48 h corridor forecast + risk (heatmap/slider) |
| GET | `/api/analyses/{id}/` | reload a previous analysis |
| GET | `/api/geocode/?q=` | address autocomplete |
| GET | `/api/health/` | liveness + DB/provider info (used by the header status pill) |

---

## Project structure

```
backend/
  config/            settings (env-driven), urls, shared HTTP session, test settings
  risk_engine/       levels.py · rules.py
  weather/           open_meteo.py · series.py · service.py
  routing/           valhalla.py · geocoding.py · geometry.py · checkpoints.py · services.py · forecast.py · models.py
  recommendations/   metrics.py · engine.py · explain.py
  api/               serializers.py · views.py · exceptions.py · urls.py
  tests/             unit + API + (opt-in) live tests
frontend/
  src/api            fetch client
  src/hooks          useAnalysis · useForecasts · useHealth · useDebounced
  src/lib            risk palette · polyline · heat-field maths · validation · formatting · view helpers (+ tests)
  src/components     TripForm · PlaceInput · RecommendationCard · RouteCard · ForecastPanel · CheckpointTable · map/*
Dockerfile · docker-compose.yml · render.yaml
```

---

## Deployment

The `Dockerfile` builds the React app and serves it from Django (WhiteNoise) next to the API, so a single web service + PostgreSQL is enough.

> **Verification status.** Tested locally: the same Django + built-React single-service mode with `DJANGO_DEBUG=false` (static assets, SPA fallback, API, `collectstatic`, health check) against PostgreSQL 16.9. **Not tested:** `docker build` / `docker compose up` (Docker was not running on the development machine), and the Render blueprint. Treat those as untested until you run them once.

**Render (blueprint included):**

1. Push this repo to GitHub (it must contain `render.yaml`, `Dockerfile` and `.dockerignore` at the root).
2. Render dashboard → **New → Blueprint** → connect GitHub → pick the repo → **Apply**. [`render.yaml`](render.yaml) creates:
   * a **PostgreSQL** database `haulwise-db` (database `haulwise`, user `haulwise`; Render generates the password), and
   * a **Docker web service** `haulwise` with `DATABASE_URL` wired to the database's internal connection string, a generated `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false` and health check `/api/health/`.
3. When prompted (or afterwards under the service's **Environment** tab), set `HTTP_USER_AGENT`, e.g. `haulwise/1.0 (contact: you@example.com)`; OSM-run services ask for a contact.
4. Wait for the first deploy. The container runs `migrate` on start, then gunicorn on Render's `$PORT`. `RENDER_EXTERNAL_HOSTNAME` is added to `ALLOWED_HOSTS` automatically, and Render terminates TLS (Django trusts `X-Forwarded-Proto`).
5. Open `https://<service>.onrender.com/api/health/` (expect `"database": {"status": "ok", "engine": "postgresql"}`), then the app itself.

Troubleshooting:
* **Health check fails with `DisallowedHost` in the logs:** add the host shown in the log to `DJANGO_ALLOWED_HOSTS` (comma separated).
* **Using a custom domain:** add it to `DJANGO_ALLOWED_HOSTS`.
* **Free-tier behaviour:** check Render's current free-tier terms. Free web services sleep when idle, so the first request after a pause can take tens of seconds, and free databases may have a limited lifetime. Wake the app before demoing.

**Any Docker host:** build the image, provide `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`; the container runs migrations and starts gunicorn on `$PORT`.

**Split hosting** (e.g. static frontend on Netlify/Vercel): build with `VITE_API_URL=https://your-api`, and set `CORS_ALLOWED_ORIGINS` on the API.

> Production note: the free public Valhalla / Photon / Nominatim / Open-Meteo endpoints are rate-limited and intended for light use. For real traffic, host your own Valhalla (or use a commercial provider) and an Open-Meteo plan via the `*_URL` / `*_API_KEY` variables — no code changes needed.

---

## Known limitations

* **ETAs assume continuous driving** with the routing provider's typical truck speeds. There is no live traffic, and no hours-of-service breaks or overnight stops, so very long trips may arrive later than shown (and weather would then be sampled at the later time).
* Forecasts are model output: Open-Meteo's grid is coarser than a road; wind is sustained 10 m speed (not gusts); snow is snowfall depth per hour, not liquid equivalent.
* **Three routes are not guaranteed.** Where the road network has only one sensible truck corridor (e.g. Seattle→Portland on I-5) re-routing produces only long detours, which are rejected; the app then shows 2 (or 1) routes with an explanation. 2 of 14 real test trips ended with 2 routes.
* **Distinctness thresholds are heuristics** (15% / 2 mi unique, 0.5 mi tolerance, 1.5× drive-time limit); they were tuned on the trips above, not on a large benchmark. Two distinct routes can still share a long common stretch, and their 3-road summaries may look alike (e.g. Miami→Orlando A and B).
* **Re-routing costs extra provider calls**: up to 4 more requests per analysis when fewer than 3 routes come back directly (typically 1; whole analyses took 2–6 s in the 14-trip test). Mind the public server's rate limits.
* Alternative routes can be close variants of each other (especially on long interstate trips where the network offers few real alternatives). Exact duplicates are collapsed.
* The weather cache is per-process (`LocMemCache`); with several workers each warms its own. Swap `CACHES` for Redis/Memcached to share it.
* Times are displayed in the browser's time zone.

---

## Loom walkthrough outline (5–10 min)

The full timed script is in [`docs/LOOM_SCRIPT.md`](docs/LOOM_SCRIPT.md). In short: demo Chicago→Dallas (cards, map, popups, table); the heatmap and 0–48 h slider; Dallas→Houston (re-routed alternatives) and Seattle→Portland (honest 2-route explanation); the risk rules and boundary interpretation; weather at ETA; the recommendation order and No Travel gate with the test run; then architecture and deployment.
