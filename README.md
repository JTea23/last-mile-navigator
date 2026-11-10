# Last Mile Navigator – data layer

PostGIS database + FastAPI backend + map-based editor for manually adding accessibility data on top of an
imported [OpenSidewalks](https://sidewalks.washington.edu/) (OSW 0.3) network for the UW Seattle campus.

## Why PostgreSQL + PostGIS
- OSW is a graph/geometry schema (nodes, edges, zones). PostGIS stores and queries it natively (bbox, nearest, routing later via pgRouting).
- Manual points and zones live in their **own table** (`accessibility_points`), so re-importing OSW never overwrites hand-entered data.
- Google Sheets can't do spatial queries or hold polygons well; keep it only as an optional export/review format.
- Free hosted options with PostGIS: Supabase, Neon. Local dev: Docker (below).

## Layout
- `db/init.sql` – schema (`osw_nodes`, `osw_edges`, `accessibility_points`)
- `backend/app/main.py` – FastAPI REST API
- `scripts/import_osw.py` – OSW GeoJSON importer
- `frontend/index.html` – click-to-add editor (Leaflet), served at `/admin`

## Run
```bash
cp .env.example .env          # set ADMIN_API_KEY
docker compose up --build     # API on :8000, editor on :8000/admin, docs on :8000/docs
```

## Import OpenSidewalks data
Get a UW/Seattle OSW dataset (e.g. from TDEI / the Taskar Center) containing `opensidewalks.edges.geojson`
and `opensidewalks.nodes.geojson`, then:
```bash
pip install "psycopg[binary]"
export DATABASE_URL=postgresql://lmn:lmn@localhost:5432/lmn
python scripts/import_osw.py ./data/seattle_osw.zip --truncate     # clipped to UW campus bbox
```
Check incline units against your dataset's schema version (OSW stores a signed fraction; the importer converts to percent).

## API
| Method | Path | Notes |
|---|---|---|
| GET | `/api/points?kind=&bbox=&verified_only=` | GeoJSON |
| GET | `/api/points/nearest?lon=&lat=&kind=parking_lot` | closest N, with `distance_m` |
| POST/PATCH/DELETE | `/api/points[/{id}]` | requires `X-API-Key` |
| GET | `/api/edges?bbox=&stairs_only=` | imported OSW edges |

Point kinds: `stairs, steep_slope, curb_ramp, elevator, accessible_entrance, obstruction, parking_lot, lime_no_go, lime_parking`.

## Next.js
```js
const r = await fetch(`${API}/api/points?kind=lime_no_go`); const geojson = await r.json();
```
Render GeoJSON with Leaflet/MapLibre/Google Maps (`map.data.addGeoJson`).

## Before production
Put the API behind HTTPS, use a long random `ADMIN_API_KEY` (or real auth), and back up the database.
