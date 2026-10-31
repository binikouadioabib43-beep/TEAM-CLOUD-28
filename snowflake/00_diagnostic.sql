-- =============================================================================
-- EcoAbidjan - 00 : Diagnostic de l'environnement Snowflake
-- A executer EN PREMIER, ligne par ligne, dans une feuille de calcul Snowsight.
-- Objectif : verifier ce qui est reellement disponible avant toute installation.
-- Note chaque resultat : les scripts suivants en dependent.
-- =============================================================================

-- 1. Compte, region, edition
SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_VERSION(), CURRENT_ROLE(), CURRENT_USER();

-- 2. Les fonctions Cortex AI dependent de la region. Si un modele n'est pas disponible
--    dans ta region, l'inference inter-regions peut etre activee par un ACCOUNTADMIN.
SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
-- Pour l'activer (ACCOUNTADMIN, a valider avec ton organisation) :
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

-- 3. Le role doit disposer du role de base de donnees SNOWFLAKE.CORTEX_USER
SHOW GRANTS OF DATABASE ROLE SNOWFLAKE.CORTEX_USER;

-- 4. Test texte de AI_COMPLETE (remplace le modele si une erreur "model not available" apparait)
SELECT AI_COMPLETE('claude-3-5-sonnet', 'Reponds uniquement par le mot OK');
SELECT AI_COMPLETE('mistral-large2', 'Reponds uniquement par le mot OK');

-- 5. Test image : necessite un stage interne avec chiffrement SNOWFLAKE_SSE (cree par 01_setup.sql)
--    puis une photo deposee dessus. A relancer apres 01_setup.sql :
-- PUT file://C:/chemin/vers/photo.jpg @ECOABIDJAN.RAW.PHOTOS_STAGE/tests/ AUTO_COMPRESS=FALSE;
-- SELECT AI_COMPLETE('claude-3-5-sonnet',
--        'Decris les dechets visibles sur cette photo en une phrase.',
--        TO_FILE('@ECOABIDJAN.RAW.PHOTOS_STAGE', 'tests/photo.jpg'));

-- 6. Entrepots et bases existants
SHOW WAREHOUSES;
SHOW DATABASES LIKE 'ECOABIDJAN';
