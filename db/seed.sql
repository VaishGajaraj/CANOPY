-- Minimal seed so the schema is queryable immediately after `docker compose up`.
-- The MVP's real data comes from the in-memory pipeline; this is just a smoke
-- row per table to prove the DDL loaded and the geometry types work.

INSERT INTO exercises (id, name, unit, started_at)
VALUES ('00000000-0000-0000-0000-0000000000e1', 'SEED EXERCISE', 'demo', now())
ON CONFLICT DO NOTHING;

INSERT INTO sources (id, source_int, label, geom, calibration)
VALUES
  ('00000000-0000-0000-0000-0000000000a1', 'rf', 'node-N',
   ST_SetSRID(ST_MakePoint(-79.0, 35.143), 4326), '{"df_sigma_deg": 3.5}'),
  ('00000000-0000-0000-0000-0000000000a2', 'sar', 'NISAR L-band', NULL,
   '{"provisional": true}')
ON CONFLICT DO NOTHING;
