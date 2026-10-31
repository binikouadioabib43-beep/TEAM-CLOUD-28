-- =============================================================================
-- EcoAbidjan - 01 : Installation (entrepot, base, schemas, role, stage photos)
-- A executer avec un role disposant des droits d'administration (ACCOUNTADMIN
-- ou SYSADMIN + SECURITYADMIN).
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- Entrepot economique : suspendu apres 60 s d'inactivite
CREATE WAREHOUSE IF NOT EXISTS ECOABIDJAN_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'EcoAbidjan - analytique et IA';

CREATE DATABASE IF NOT EXISTS ECOABIDJAN COMMENT = 'EcoAbidjan - gestion et valorisation des dechets';
CREATE SCHEMA IF NOT EXISTS ECOABIDJAN.RAW       COMMENT = 'Fichiers bruts (photos) et resultats IA bruts';
CREATE SCHEMA IF NOT EXISTS ECOABIDJAN.CORE      COMMENT = 'Copie des tables operationnelles';
CREATE SCHEMA IF NOT EXISTS ECOABIDJAN.ANALYTICS COMMENT = 'Vues du tableau de bord';

-- Role applicatif utilise par le backend FastAPI
CREATE ROLE IF NOT EXISTS ECOABIDJAN_APP;
GRANT USAGE ON WAREHOUSE ECOABIDJAN_WH TO ROLE ECOABIDJAN_APP;
GRANT USAGE ON DATABASE ECOABIDJAN TO ROLE ECOABIDJAN_APP;
GRANT USAGE, CREATE TABLE, CREATE VIEW ON ALL SCHEMAS IN DATABASE ECOABIDJAN TO ROLE ECOABIDJAN_APP;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN DATABASE ECOABIDJAN TO ROLE ECOABIDJAN_APP;
GRANT SELECT ON FUTURE VIEWS IN DATABASE ECOABIDJAN TO ROLE ECOABIDJAN_APP;
-- Acces aux fonctions Cortex AI
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE ECOABIDJAN_APP;

-- Stage interne pour les photos. Le chiffrement cote serveur (SNOWFLAKE_SSE) est
-- requis pour que Cortex puisse lire les images via TO_FILE.
CREATE STAGE IF NOT EXISTS ECOABIDJAN.RAW.PHOTOS_STAGE
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Photos des signalements de depots sauvages';
GRANT READ, WRITE ON STAGE ECOABIDJAN.RAW.PHOTOS_STAGE TO ROLE ECOABIDJAN_APP;

-- Utilisateur technique du backend (decommenter et choisir un mot de passe fort,
-- ou mieux : authentification par paire de cles RSA).
-- CREATE USER IF NOT EXISTS ECOABIDJAN_SVC
--   PASSWORD = '<mot-de-passe-fort>'
--   DEFAULT_ROLE = ECOABIDJAN_APP
--   DEFAULT_WAREHOUSE = ECOABIDJAN_WH
--   DEFAULT_NAMESPACE = ECOABIDJAN.CORE
--   MUST_CHANGE_PASSWORD = FALSE;
-- GRANT ROLE ECOABIDJAN_APP TO USER ECOABIDJAN_SVC;

-- Pour tester toi-meme avec ton utilisateur :
-- GRANT ROLE ECOABIDJAN_APP TO USER <TON_UTILISATEUR>;
