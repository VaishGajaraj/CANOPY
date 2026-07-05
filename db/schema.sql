-- CANOPY signature library — schema-first (spec sec 4). THIS IS THE MOAT.
--
-- Design principle: a detection is {when, where, feature_vector, confidence,
-- source_int} regardless of modality. RF bearings and SAR coherence-loss
-- patches are the SAME row shape. The library compounds because every confirmed
-- detection becomes a reusable signature.
--
-- The one rule that protects the whole thesis: the NISAR worker inserts into
-- `detections` and `signatures` with NO NEW COLUMNS. If you ever add a
-- `sar_only` table, stop — the platform claim is breaking.
--
-- Postgres + PostGIS (geospatial) + TimescaleDB (time-series RF). One database.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- Sensors / nodes, any modality --------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_int   text NOT NULL CHECK (source_int IN ('rf','sar')),  -- extensible
  label        text,
  geom         geometry(Point, 4326),        -- node emplacement (null for spaceborne)
  calibration  jsonb,                         -- per-node cal: antenna array, cable delays, df_sigma_deg
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Campaign container (an exercise, an AOI-monitoring period) -----------------
CREATE TABLE IF NOT EXISTS exercises (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL,
  unit       text,
  aoi        geometry(Polygon, 4326),
  started_at timestamptz,
  ended_at   timestamptz
);

-- Critical-phase windows (e.g. the assault) drive the phase term of the
-- targetability score. Radiating during the assault is the cardinal sin.
CREATE TABLE IF NOT EXISTS critical_windows (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id uuid REFERENCES exercises(id) ON DELETE CASCADE,
  label       text NOT NULL,
  started_at  timestamptz NOT NULL,
  ended_at    timestamptz NOT NULL
);

-- The compounding asset: what a thing looks like, so it is re-findable -------
CREATE TABLE IF NOT EXISTS signatures (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_int        text NOT NULL,
  emitter_type      text,   -- tac_vhf|tac_uhf|cellular|bt_region|gps_anomaly|wideband|sar_disturbance
  feature_vector    jsonb NOT NULL,             -- modality-specific features, uniform slot
  label             text,                        -- analyst-assigned, nullable
  analyst_confirmed boolean NOT NULL DEFAULT false,
  first_seen        timestamptz,
  last_seen         timestamptz,
  times_seen        integer NOT NULL DEFAULT 0
);

-- Atomic sensor-agnostic detection ------------------------------------------
CREATE TABLE IF NOT EXISTS detections (
  id            uuid NOT NULL DEFAULT gen_random_uuid(),
  exercise_id   uuid REFERENCES exercises(id),
  source_id     uuid REFERENCES sources(id),
  source_int    text NOT NULL,
  observed_at   timestamptz NOT NULL,
  geom          geometry(Geometry, 4326),     -- Point=fix, LineString=bearing, Polygon=SAR patch
  confidence    real CHECK (confidence BETWEEN 0 AND 1),
  features      jsonb NOT NULL,               -- RF: {center_hz,bw_hz,burst_ms,duty,bearing_deg}
                                              -- SAR: {coh_drop, area_m2}
  emitter_type  text,
  signature_id  uuid REFERENCES signatures(id),
  PRIMARY KEY (id, observed_at)               -- Timescale needs the time col in the PK
);
-- TimescaleDB hypertable on the RF firehose.
SELECT create_hypertable('detections','observed_at', if_not_exists => TRUE);

-- Fused geolocation fix from >=2 detections ---------------------------------
CREATE TABLE IF NOT EXISTS fixes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id     uuid REFERENCES exercises(id),
  signature_id    uuid REFERENCES signatures(id),
  geom            geometry(Point, 4326),
  err_semimajor_m real,     -- error ellipse — HONEST uncertainty, ALWAYS populated
  err_semiminor_m real,
  err_orient_deg  real,
  cep50_m         real,
  gdop            real,
  n_contributors  int,
  method          text CHECK (method IN ('bearing_intersection','coherence_patch')),
  fixed_at        timestamptz NOT NULL
);

-- Persistent watch — the flywheel seed --------------------------------------
CREATE TABLE IF NOT EXISTS watches (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  signature_id uuid REFERENCES signatures(id),
  aoi          geometry(Polygon, 4326),
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS watch_hits (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  watch_id     uuid REFERENCES watches(id),
  detection_id uuid,
  fired_at     timestamptz NOT NULL DEFAULT now()
);

-- Indexes -------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_detections_exercise ON detections (exercise_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_detections_signature ON detections (signature_id);
CREATE INDEX IF NOT EXISTS idx_detections_geom ON detections USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_detections_emitter ON detections (emitter_type);
CREATE INDEX IF NOT EXISTS idx_fixes_exercise ON fixes (exercise_id, fixed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signatures_type ON signatures (source_int, emitter_type);

-- Retention / PII note (spec sec 11, sec 12): friendly-force cellular
-- detections can constitute PII. `features` for those rows must store
-- band/timing, NOT decoded identifiers, and personal-device detections should
-- be purgeable per exercise. A per-exercise purge is a first-class operation:
--   DELETE FROM detections WHERE exercise_id = $1 AND emitter_type = 'cellular';
