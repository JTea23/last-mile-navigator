import json, os, secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, field_validator

Kind = Literal["stairs", "steep_slope", "curb_ramp", "elevator", "accessible_entrance",
               "obstruction", "parking_lot", "lime_no_go", "lime_parking"]

pool = ConnectionPool(os.environ["DATABASE_URL"], kwargs={"row_factory": dict_row}, open=False)


@asynccontextmanager
async def lifespan(_):
    pool.open()
    yield
    pool.close()


app = FastAPI(title="Last Mile Navigator API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def require_key(x_api_key: str = Header(default="")):
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Missing or invalid X-API-Key")


class PointIn(BaseModel):
    kind: Kind
    name: Optional[str] = None
    description: Optional[str] = None
    geometry: dict                      # GeoJSON Point or Polygon, [lon, lat]
    props: dict = Field(default_factory=dict)
    verified: bool = False

    @field_validator("geometry")
    @classmethod
    def geom_ok(cls, g):
        if g.get("type") not in ("Point", "Polygon") or "coordinates" not in g:
            raise ValueError("geometry must be a GeoJSON Point or Polygon")
        return g


class PointPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    props: Optional[dict] = None
    verified: Optional[bool] = None


def bbox_sql(bbox: Optional[str]):
    if not bbox:
        return "TRUE", []
    try:
        a = [float(x) for x in bbox.split(",")]
        assert len(a) == 4
    except Exception:
        raise HTTPException(422, "bbox must be minLon,minLat,maxLon,maxLat")
    return "geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)", a


def collection(rows):
    feats = [{"type": "Feature", "id": r.pop("id"), "geometry": r.pop("geometry"), "properties": r} for r in rows]
    return {"type": "FeatureCollection", "features": feats}


POINT_COLS = "id, kind, name, description, props, source, verified, ST_AsGeoJSON(geom)::json AS geometry"


@app.get("/api/health")
def health():
    with pool.connection() as c:
        c.execute("SELECT 1")
    return {"ok": True}


@app.get("/api/points")
def list_points(kind: Optional[Kind] = None, bbox: Optional[str] = None, verified_only: bool = False):
    where, args = bbox_sql(bbox)
    if kind:
        where += " AND kind=%s"; args.append(kind)
    if verified_only:
        where += " AND verified"
    with pool.connection() as c:
        return collection(c.execute(f"SELECT {POINT_COLS} FROM accessibility_points WHERE {where}", args).fetchall())


@app.get("/api/points/nearest")
def nearest(lon: float, lat: float, kind: Kind, limit: int = Query(3, ge=1, le=20)):
    sql = f"""SELECT {POINT_COLS}, ROUND(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)) AS distance_m
              FROM accessibility_points WHERE kind=%s
              ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s,%s),4326) LIMIT %s"""
    with pool.connection() as c:
        return collection(c.execute(sql, [lon, lat, kind, lon, lat, limit]).fetchall())


@app.post("/api/points", status_code=201, dependencies=[Depends(require_key)])
def create_point(p: PointIn):
    sql = f"""INSERT INTO accessibility_points (kind,name,description,geom,props,verified)
              VALUES (%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,%s)
              RETURNING {POINT_COLS}"""
    with pool.connection() as c:
        try:
            row = c.execute(sql, [p.kind, p.name, p.description, json.dumps(p.geometry), Jsonb(p.props), p.verified]).fetchone()
        except Exception as e:
            raise HTTPException(422, f"Invalid geometry: {e}")
    return collection([row])["features"][0]


@app.patch("/api/points/{pid}", dependencies=[Depends(require_key)])
def patch_point(pid: int, p: PointPatch):
    sets, args = [], []
    for k, v in p.model_dump(exclude_unset=True).items():
        sets.append(f"{k}=%s"); args.append(Jsonb(v) if k == "props" else v)
    if not sets:
        raise HTTPException(422, "Nothing to update")
    with pool.connection() as c:
        row = c.execute(f"UPDATE accessibility_points SET {','.join(sets)}, updated_at=now() WHERE id=%s RETURNING {POINT_COLS}", args + [pid]).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return collection([row])["features"][0]


@app.delete("/api/points/{pid}", status_code=204, dependencies=[Depends(require_key)])
def delete_point(pid: int):
    with pool.connection() as c:
        if not c.execute("DELETE FROM accessibility_points WHERE id=%s RETURNING id", [pid]).fetchone():
            raise HTTPException(404, "Not found")


@app.get("/api/edges")
def edges(bbox: str, stairs_only: bool = False, limit: int = Query(5000, le=20000)):
    where, args = bbox_sql(bbox)
    if stairs_only:
        where += " AND highway='steps'"
    sql = f"""SELECT id, highway, footway, incline_pct, surface, width_m, length_m, ST_AsGeoJSON(geom)::json AS geometry
              FROM osw_edges WHERE {where} LIMIT %s"""
    with pool.connection() as c:
        return collection(c.execute(sql, args + [limit]).fetchall())


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND.exists():
    app.mount("/admin", StaticFiles(directory=FRONTEND, html=True), name="admin")
