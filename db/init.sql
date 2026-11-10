-- Last Mile Navigator: PostGIS schema
-- Layer 1: imported OpenSidewalks (OSW 0.3) network. Re-import any time.
-- Layer 2: manually entered accessibility points/zones (never overwritten by imports).
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE osw_nodes (
  id    text PRIMARY KEY,                       -- OSW _id
  geom  geometry(Point,4326) NOT NULL,
  props jsonb NOT NULL DEFAULT '{}'             -- full original properties (kerb, tactile_paving, ...)
);
CREATE INDEX osw_nodes_geom ON osw_nodes USING gist (geom);

CREATE TABLE osw_edges (
  id          text PRIMARY KEY,                 -- OSW _id
  geom        geometry(LineString,4326) NOT NULL,
  u_id        text,                             -- OSW _u_id (start node)
  v_id        text,                             -- OSW _v_id (end node)
  highway     text,                             -- footway | steps | pedestrian | ...
  footway     text,                             -- sidewalk | crossing | ...
  incline_pct real,                             -- signed percent grade (+ uphill in u->v direction)
  surface     text,
  width_m     real,
  length_m    real,
  props       jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX osw_edges_geom ON osw_edges USING gist (geom);
CREATE INDEX osw_edges_type ON osw_edges (highway, footway);

CREATE TABLE accessibility_points (
  id          bigserial PRIMARY KEY,
  kind        text NOT NULL CHECK (kind IN (
                'stairs','steep_slope','curb_ramp','elevator','accessible_entrance',
                'obstruction','parking_lot','lime_no_go','lime_parking')),
  name        text,
  description text,
  geom        geometry(Geometry,4326) NOT NULL  -- Point, or Polygon for zones/lots
              CHECK (GeometryType(geom) IN ('POINT','POLYGON')),
  props       jsonb NOT NULL DEFAULT '{}',      -- free-form: grade, hours, photo_url, ...
  source      text NOT NULL DEFAULT 'manual',
  verified    boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX accessibility_points_geom ON accessibility_points USING gist (geom);
CREATE INDEX accessibility_points_kind ON accessibility_points (kind);
