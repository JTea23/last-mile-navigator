"""Import an OpenSidewalks (OSW 0.3) dataset into PostGIS.

Usage:  python scripts/import_osw.py path/to/dataset_dir_or.zip [--bbox minLon,minLat,maxLon,maxLat] [--all] [--truncate]
Expects opensidewalks.edges.geojson and opensidewalks.nodes.geojson (OSW 0.3 filenames).
Manual points in accessibility_points are never touched.
"""
import argparse, json, os, zipfile
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb

UW_BBOX = (-122.3150, 47.6480, -122.2900, 47.6620)   # rough UW Seattle campus; adjust as needed


def read(src, suffix):
    src = Path(src)
    if src.suffix == ".zip":
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                if n.endswith(suffix):
                    return json.loads(z.read(n))
    else:
        for f in src.rglob("*" + suffix):
            return json.loads(f.read_text())
    raise SystemExit(f"{suffix} not found in {src}")


def incline_pct(v):
    """OSW stores incline as a signed fraction (0.05 = 5%); tolerate '5%' strings."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            s = v.strip()
            return float(s.rstrip("%")) if s.endswith("%") else float(s) * 100
        return float(v) * 100
    except ValueError:
        return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def in_bbox(geom, b):
    if not b:
        return True
    pts = geom["coordinates"] if geom["type"] == "LineString" else [geom["coordinates"]]
    return any(b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3] for p in pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--bbox", help="minLon,minLat,maxLon,maxLat (default: UW campus area)")
    ap.add_argument("--all", action="store_true", help="import everything, ignore bbox")
    ap.add_argument("--truncate", action="store_true", help="clear osw_nodes/osw_edges first")
    a = ap.parse_args()
    bbox = None if a.all else (tuple(map(float, a.bbox.split(","))) if a.bbox else UW_BBOX)

    nodes = [f for f in read(a.source, "nodes.geojson")["features"] if in_bbox(f["geometry"], bbox)]
    edges = [f for f in read(a.source, "edges.geojson")["features"] if in_bbox(f["geometry"], bbox)]

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        if a.truncate:
            cur.execute("TRUNCATE osw_nodes, osw_edges")
        nrows = [(str(f["properties"].get("_id") or f.get("id")), json.dumps(f["geometry"]), Jsonb(f["properties"]))
                 for f in nodes if f["geometry"]["type"] == "Point" and (f["properties"].get("_id") or f.get("id"))]
        cur.executemany(
            """INSERT INTO osw_nodes (id,geom,props) VALUES (%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s)
               ON CONFLICT (id) DO UPDATE SET geom=EXCLUDED.geom, props=EXCLUDED.props""", nrows)
        rows = []
        for f in edges:
            p = f["properties"]
            eid = p.get("_id") or f.get("id")
            if not eid or f["geometry"]["type"] != "LineString":
                continue
            rows.append((str(eid), json.dumps(f["geometry"]), p.get("_u_id"), p.get("_v_id"), p.get("highway"),
                         p.get("footway"), incline_pct(p.get("incline")), p.get("surface"), num(p.get("width")),
                         num(p.get("length")), Jsonb(p)))
        cur.executemany(
            """INSERT INTO osw_edges (id,geom,u_id,v_id,highway,footway,incline_pct,surface,width_m,length_m,props)
               VALUES (%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET geom=EXCLUDED.geom, u_id=EXCLUDED.u_id, v_id=EXCLUDED.v_id,
               highway=EXCLUDED.highway, footway=EXCLUDED.footway, incline_pct=EXCLUDED.incline_pct,
               surface=EXCLUDED.surface, width_m=EXCLUDED.width_m, length_m=EXCLUDED.length_m, props=EXCLUDED.props""",
            rows)
    print(f"Imported {len(nrows)} nodes, {len(rows)} edges")


if __name__ == "__main__":
    main()
