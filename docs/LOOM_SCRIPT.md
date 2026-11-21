# Loom walkthrough script (target 8–9 minutes, hard limit 10)

**Before recording**
- Open the hosted app and run one analysis first, so a sleeping free-tier server is awake.
- Tabs: (1) hosted app, (2) GitHub repo, (3) VS Code with `backend/risk_engine/rules.py`, `backend/routing/route_search.py`, `backend/recommendations/engine.py`, (4) a terminal in `backend/` with the venv ready.
- Have the test command ready: `.\.venv\Scripts\python -m pytest -o addopts=""`.
- Weather is live, so most trips will show "Low". That's fine. Explain that the risky paths are proven by tests, and point at any yellow/red in the 48-hour strip if the forecast has some.

---

## 0:00 – 0:45 · Intro
> "This is HaulWise, my submission for the Spotter full-stack assessment: a React + Django app that helps a truck driver pick the safest route using weather, load weight and travel time. I'll demo it, then walk through the routing, weather, risk and recommendation logic, and finish with architecture and deployment."

Show the empty dashboard: form on the left, map on the right, status pill in the header ("All systems operational", hover to show DB and providers).

## 0:45 – 2:30 · Demo: a normal trip
1. Type **Chicago, IL** and pick the suggestion (autocomplete: Photon with Nominatim fallback). Then **Dallas, TX**.
2. Departure: keep the next hour. Load: **42,000 lb**. Point at the hint: "over 40,000 lb, 35 mph wind becomes Severe and 45 mph becomes No Travel".
3. Checkpoint interval **25 mi**. Click **Find safest route**.
4. Walk the result:
   - **Recommendation card**: read the headline. "It explains *why*, using the PDF's priority order."
   - **Route cards** A/B/C: distance, drive time, arrival, the risk bar (miles per risk level), severe/high/No Travel miles, average risk.
   - **Map**: three colored routes, the recommended one highlighted; hover a route to show the tooltip (summary, distance, ETA); click a checkpoint dot to show the popup (ETA, wind/rain/snow, per-factor risk, the forecast hour used).
   - **Checkpoint table**: mile, ETA, wind, rain, snow, risk. Click a row and the map popup opens.

## 2:30 – 3:30 · Heatmap and 0–48 h slider
- "Trip view shows the weather the truck meets at each checkpoint's ETA."
- Drag the slider: "Now every checkpoint and the heatmap show the forecast at one moment, departure + N hours. This needs no network call; the 49-hour series was loaded once."
- Point at the strip behind the slider: "worst risk anywhere on the route in each hour". Press **Play**, then **Back to trip view**.
- "The heatmap is interpolated only from real forecast samples within about 14 miles of the route. Nowhere else is painted."

## 3:30 – 4:45 · Three distinct routes (the hard part)
1. Run **Dallas, TX → Houston, TX**. "Valhalla's truck mode suggests only one route here."
2. Show Routes B and C with the **Alternative corridor** chip and the info note.
3. Open `route_search.py` and explain:
   - Ask directly first, then drop near-duplicates. A route is new only if ≥ 15% of it is more than half a mile from every other route. Valhalla's own "three" Dallas→Fort Worth routes included two identical roads.
   - Re-route with small `exclude_polygons` blocks on the routes found so far. The public server caps polygons at 10 km circumference, which I measured.
   - Reject detours over 1.5× the fastest drive time. Every route is real and gets the full pipeline.
4. Run **Seattle, WA → Portland, OR**: two routes plus the amber explanation. "When a third genuinely different route doesn't exist, it says so instead of inventing one."

## 4:45 – 6:15 · Weather and risk logic
- `risk_engine/rules.py`: the threshold tables. "The PDF's ranges overlap at the edges and leave gaps, so every band is lower-bound inclusive. 35 mph is High and 0.25 in/hr rain is High; rain 1.00 and snow 3.0 stay Severe because No Travel is a strict 'greater than'."
- Load rules: ≥ 55 mph No Travel for any load; 45–54 with > 30,000 lb No Travel; 35–44 with > 40,000 lb Severe. A checkpoint takes the highest of wind, rain and snow.
- Weather at ETA: ETAs come from Valhalla's per-maneuver times, not one average speed. Wind uses the nearest hour, and rain/snow the hour containing the ETA (Open-Meteo stamps totals at the end of the hour). Past the 16-day horizon a checkpoint is "unavailable", never "Low".
- Efficiency: snapped grid, de-duplication across routes, batching and caching. 122 checkpoints became 3 weather requests on Chicago→Dallas.

## 6:15 – 7:15 · Recommendation and safety
- `recommendations/engine.py`: the lexicographic key, i.e. fewest Severe miles, fewest High miles, lowest average risk, shortest time. "Risk *miles* use the road length each checkpoint represents, not a checkpoint count."
- No Travel gate: a route with any No Travel segment never beats one without. If all routes have it, the app says "No safe route found".
- Terminal: run the tests and show **187 passed**. Mention the boundary tests at 25/35/45/55 mph and at 30,000/40,000 lb.

## 7:15 – 8:30 · Architecture, quality and deployment
- Backend apps: `risk_engine`, `weather`, `routing`, `recommendations`, `api`. Views are thin, and errors share one JSON format.
- Frontend: React + Vite + Tailwind + React-Leaflet. The heat layer is a custom canvas layer: geometry is rebuilt on map move, and the slider only re-evaluates values.
- One Docker image: Django serves the built React app through WhiteNoise. PostgreSQL. Render blueprint. Show `render.yaml` briefly.
- Honest limitations: ETAs have no traffic or hours-of-service breaks, three routes aren't guaranteed on single-corridor trips, and the free public APIs are rate-limited.

## 8:30 – 9:00 · Close
> "To sum up: three genuinely distinct truck routes where they exist, weather sampled at the truck's ETA, the PDF's exact risk and load rules with tested boundaries, a recommendation that explains itself, and a real-data heatmap with a 48-hour slider. Thanks for watching."
