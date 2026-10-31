-- =============================================================================
-- EcoAbidjan - 05 : Analyse des photos avec Snowflake Cortex AI
-- Le backend appelle deja AI_COMPLETE photo par photo (AI_PROVIDER=snowflake).
-- Ce script permet en plus une analyse en lot de toutes les photos du stage.
--
-- A VERIFIER dans ton compte avant usage (voir 00_diagnostic.sql) :
--   - le modele multimodal choisi est disponible dans ta region
--     (sinon CORTEX_ENABLED_CROSS_REGION) ;
--   - le stage utilise ENCRYPTION = SNOWFLAKE_SSE ;
--   - le role a SNOWFLAKE.CORTEX_USER.
-- L'analyse d'images est facturee en credits Cortex : teste d'abord sur quelques photos.
-- =============================================================================

USE ROLE ECOABIDJAN_APP;
USE WAREHOUSE ECOABIDJAN_WH;
USE SCHEMA ECOABIDJAN.RAW;

-- Rafraichir la table de repertoire apres des depots via PUT
ALTER STAGE PHOTOS_STAGE REFRESH;

-- Photos presentes sur le stage
SELECT RELATIVE_PATH, SIZE, LAST_MODIFIED FROM DIRECTORY(@PHOTOS_STAGE) ORDER BY LAST_MODIFIED DESC;

-- Test sur une seule photo
SELECT RELATIVE_PATH, AI_COMPLETE(
  'claude-3-5-sonnet',
  'Liste les matieres de dechets visibles (plastique, carton, aluminium, verre, organique, textile) en une phrase.',
  TO_FILE('@PHOTOS_STAGE', RELATIVE_PATH)
) AS REPONSE
FROM DIRECTORY(@PHOTOS_STAGE)
LIMIT 1;

-- Analyse en lot des photos pas encore analysees (meme prompt que le backend, version v1)
INSERT INTO AI_BATCH_RESULTS (RELATIVE_PATH, MODEL, PROMPT_VERSION, RESPONSE)
SELECT
  D.RELATIVE_PATH,
  'claude-3-5-sonnet',
  'v1',
  AI_COMPLETE(
    'claude-3-5-sonnet',
    'Tu es un expert en gestion des dechets a Abidjan. Analyse cette photo d''un depot sauvage. '
    || 'Identifie les matieres visibles et estime le volume et le poids du tas. Reponds UNIQUEMENT par un JSON valide : '
    || '{"materiaux":[{"code":"PLASTIQUE|CARTON|ALUMINIUM|VERRE|ORGANIQUE|TEXTILE|AUTRE","part":0.0,"confiance":0.0}],'
    || '"volume_m3":0.0,"poids_kg":0.0,"confiance":0.0,"resume":"une phrase en francais"}',
    TO_FILE('@PHOTOS_STAGE', D.RELATIVE_PATH)
  )
FROM DIRECTORY(@PHOTOS_STAGE) D
WHERE D.RELATIVE_PATH NOT IN (SELECT RELATIVE_PATH FROM AI_BATCH_RESULTS)
LIMIT 20;

-- Lecture structuree des resultats
SELECT
  RELATIVE_PATH,
  TRY_PARSE_JSON(REGEXP_SUBSTR(RESPONSE, '\\{.*\\}', 1, 1, 's')) AS J,
  J:poids_kg::FLOAT   AS POIDS_KG_ESTIME,
  J:volume_m3::FLOAT  AS VOLUME_M3_ESTIME,
  J:confiance::FLOAT  AS CONFIANCE,
  J:resume::VARCHAR   AS RESUME
FROM AI_BATCH_RESULTS
ORDER BY ANALYZED_AT DESC;
