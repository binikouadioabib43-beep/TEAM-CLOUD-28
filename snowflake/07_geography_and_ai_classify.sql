-- =============================================================================
-- EcoAbidjan - 07 : Donnees geographiques (GEOGRAPHY) et classification des photos
--                    avec Cortex AI_CLASSIFY
-- Prerequis : 01 a 05 executes, donnees synchronisees depuis l'application
-- (admin > Snowflake > Synchroniser) et photos deposees sur le stage.
-- A VERIFIER : AI_CLASSIFY sur images doit etre disponible dans ta region
-- (sinon CORTEX_ENABLED_CROSS_REGION). Facturation en credits Cortex.
-- =============================================================================

USE ROLE ECOABIDJAN_APP;
USE WAREHOUSE ECOABIDJAN_WH;
USE SCHEMA ECOABIDJAN.ANALYTICS;

-- 1. Signalements et points relais en GEOGRAPHY -------------------------------
CREATE OR REPLACE VIEW V_SIGNALEMENTS_GEO AS
SELECT R.ID, R.STATUS, R.CREATED_AT, R.AI_ESTIMATED_WEIGHT_KG, C.NAME AS COMMUNE,
       ST_MAKEPOINT(R.LONGITUDE, R.LATITUDE) AS POSITION
FROM CORE.REPORTS R
LEFT JOIN CORE.COMMUNES C ON C.ID = R.COMMUNE_ID;

CREATE OR REPLACE VIEW V_POINTS_RELAIS_GEO AS
SELECT ID, NAME, ST_MAKEPOINT(LONGITUDE, LATITUDE) AS POSITION
FROM CORE.RELAY_POINTS WHERE IS_ACTIVE;

-- Doublons probables : signalements ouverts a moins de 50 m l'un de l'autre
CREATE OR REPLACE VIEW V_DOUBLONS_SIGNALEMENTS AS
SELECT A.ID AS SIGNALEMENT_A, B.ID AS SIGNALEMENT_B, ROUND(ST_DISTANCE(A.POSITION, B.POSITION)) AS DISTANCE_M
FROM V_SIGNALEMENTS_GEO A
JOIN V_SIGNALEMENTS_GEO B ON A.ID < B.ID AND ST_DWITHIN(A.POSITION, B.POSITION, 50)
WHERE A.STATUS IN ('SIGNALE', 'CONFIRME') AND B.STATUS IN ('SIGNALE', 'CONFIRME');

-- Point relais le plus proche de chaque signalement ouvert
CREATE OR REPLACE VIEW V_SIGNALEMENT_POINT_RELAIS_PROCHE AS
SELECT S.ID, S.COMMUNE, P.NAME AS POINT_RELAIS, ROUND(ST_DISTANCE(S.POSITION, P.POSITION)) AS DISTANCE_M
FROM V_SIGNALEMENTS_GEO S CROSS JOIN V_POINTS_RELAIS_GEO P
WHERE S.STATUS IN ('SIGNALE', 'CONFIRME')
QUALIFY ROW_NUMBER() OVER (PARTITION BY S.ID ORDER BY ST_DISTANCE(S.POSITION, P.POSITION)) = 1;

-- 2. Classification des photos avec AI_CLASSIFY --------------------------------
USE SCHEMA ECOABIDJAN.RAW;
ALTER STAGE PHOTOS_STAGE REFRESH;

CREATE TABLE IF NOT EXISTS AI_CLASSIFY_RESULTS (
  RELATIVE_PATH VARCHAR,
  RESULTAT VARIANT,
  ANALYZED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Test sur une photo : matieres presentes (plusieurs etiquettes possibles)
SELECT RELATIVE_PATH,
       AI_CLASSIFY(
         TO_FILE('@PHOTOS_STAGE', RELATIVE_PATH),
         ['plastique', 'carton', 'aluminium', 'verre', 'organique', 'textile', 'gravats'],
         {'task_description': 'Identifie les matieres de dechets visibles sur cette photo de depot sauvage a Abidjan',
          'output_mode': 'multi'}
       ) AS MATIERES
FROM DIRECTORY(@PHOTOS_STAGE)
LIMIT 1;

-- En lot : photos non encore classees
INSERT INTO AI_CLASSIFY_RESULTS (RELATIVE_PATH, RESULTAT)
SELECT D.RELATIVE_PATH,
       AI_CLASSIFY(
         TO_FILE('@PHOTOS_STAGE', D.RELATIVE_PATH),
         ['plastique', 'carton', 'aluminium', 'verre', 'organique', 'textile', 'gravats'],
         {'task_description': 'Identifie les matieres de dechets visibles sur cette photo de depot sauvage a Abidjan',
          'output_mode': 'multi'}
       )
FROM DIRECTORY(@PHOTOS_STAGE) D
WHERE D.RELATIVE_PATH NOT IN (SELECT RELATIVE_PATH FROM AI_CLASSIFY_RESULTS)
LIMIT 20;

-- Frequence de chaque matiere detectee
SELECT L.VALUE::VARCHAR AS MATIERE, COUNT(*) AS PHOTOS
FROM AI_CLASSIFY_RESULTS, LATERAL FLATTEN(INPUT => RESULTAT:labels) L
GROUP BY 1 ORDER BY 2 DESC;

-- Niveau d'urgence d'un signalement a partir de sa description (texte)
SELECT ID, DESCRIPTION,
       AI_CLASSIFY(DESCRIPTION, ['urgent : risque sanitaire', 'a traiter cette semaine', 'peu genant']):labels[0]::VARCHAR AS URGENCE
FROM ECOABIDJAN.CORE.REPORTS
WHERE DESCRIPTION IS NOT NULL
LIMIT 20;
