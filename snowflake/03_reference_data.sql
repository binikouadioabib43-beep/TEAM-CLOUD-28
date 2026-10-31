-- =============================================================================
-- EcoAbidjan - 03 : Referentiel initial (matieres et tarifs)
-- Utile pour tester les vues avant la premiere synchronisation.
-- Attention : la synchronisation depuis le backend remplace ces lignes par
-- celles de la base operationnelle (qui reste la source de verite).
-- =============================================================================

USE SCHEMA ECOABIDJAN.CORE;

INSERT INTO MATERIALS (ID, CODE, NAME, DESCRIPTION, IS_RECYCLABLE, IS_ACTIVE)
SELECT * FROM VALUES
  (1, 'CARTON', 'Carton', 'Cartons d''emballage', TRUE, TRUE),
  (2, 'PLASTIQUE', 'Plastique', 'Bouteilles PET, bidons, sachets', TRUE, TRUE),
  (3, 'ALUMINIUM', 'Aluminium', 'Canettes, barquettes', TRUE, TRUE)
WHERE NOT EXISTS (SELECT 1 FROM MATERIALS);

-- Tarifs de reference modifiables (FCFA/kg) ; VALID_TO NULL = tarif en vigueur
INSERT INTO TARIFFS (ID, MATERIAL_ID, PRICE_FCFA_PER_KG, VALID_FROM, VALID_TO, NOTE)
SELECT * FROM VALUES
  (1, 1, 200, '2025-01-01'::TIMESTAMP_NTZ, NULL, 'Referentiel initial'),
  (2, 2, 250, '2025-01-01'::TIMESTAMP_NTZ, NULL, 'Referentiel initial'),
  (3, 3, 300, '2025-01-01'::TIMESTAMP_NTZ, NULL, 'Referentiel initial')
WHERE NOT EXISTS (SELECT 1 FROM TARIFFS);

-- Exemple : changer un tarif en conservant l'historique
-- UPDATE TARIFFS SET VALID_TO = CURRENT_TIMESTAMP() WHERE MATERIAL_ID = 2 AND VALID_TO IS NULL;
-- INSERT INTO TARIFFS (ID, MATERIAL_ID, PRICE_FCFA_PER_KG, VALID_FROM, NOTE)
--   VALUES (4, 2, 275, CURRENT_TIMESTAMP(), 'Revalorisation plastique');
