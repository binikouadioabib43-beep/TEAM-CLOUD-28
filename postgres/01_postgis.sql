-- =============================================================================
-- EcoAbidjan - PostgreSQL / PostGIS (base operationnelle de production)
-- 1. Creer la base :  CREATE DATABASE ecoabidjan;
-- 2. Lancer une fois l'application avec DATABASE_URL pointant vers cette base :
--    elle cree les tables et le referentiel automatiquement.
-- 3. Executer ce script pour ajouter les colonnes geographiques et les index spatiaux.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- Colonnes geographiques calculees a partir de latitude/longitude (WGS84)
ALTER TABLE reports ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;
ALTER TABLE relay_points ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;
ALTER TABLE declarations ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;
ALTER TABLE communes ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
  GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography) STORED;

CREATE INDEX IF NOT EXISTS idx_reports_geom      ON reports      USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_relay_points_geom ON relay_points USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_declarations_geom ON declarations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_reports_status    ON reports (status, created_at);

-- Exemples de requetes spatiales -------------------------------------------------

-- Points relais a moins de 3 km d'une position, du plus proche au plus lointain
-- SELECT name, ST_Distance(geom, ST_MakePoint(-3.99, 5.36)::geography) / 1000 AS km
-- FROM relay_points
-- WHERE is_active AND ST_DWithin(geom, ST_MakePoint(-3.99, 5.36)::geography, 3000)
-- ORDER BY km;

-- Doublons probables : signalements ouverts a moins de 50 m les uns des autres
-- SELECT a.id, b.id, ST_Distance(a.geom, b.geom) AS metres
-- FROM reports a JOIN reports b ON a.id < b.id AND ST_DWithin(a.geom, b.geom, 50)
-- WHERE a.status IN ('SIGNALE','CONFIRME') AND b.status IN ('SIGNALE','CONFIRME');
