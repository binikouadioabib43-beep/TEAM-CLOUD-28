# EcoAbidjan — Règles métier et simulation du projet pilote

Document de référence pour les planches de présentation. Tous les chiffres viennent de la simulation
(`python -m backend.app.simulate`) et sont visibles dans l'application : **admin → Projet pilote**.
La simulation est reproductible : graine aléatoire fixe, donc mêmes résultats à chaque exécution.

## 1. Périmètre du projet pilote

| Contrainte du hackathon | EcoAbidjan |
|---|---|
| Au moins 4 communes | **Yopougon, Abobo, Cocody, Koumassi** |
| Au moins 500 ménages | **500 ménages** |
| Au moins 200 commerçants | **200 commerçants** (maquis, boutiques, supermarchés, commerces du marché, bars) |
| Seuil Y, barème et conversion des points définis et justifiés | Sections 3 à 5 ci-dessous |
| Snowflake utilisé et visible | Section 6 |

S'y ajoutent 150 citoyens qui signalent des dépôts sauvages. La répartition entre communes suit à peu près
leur population : Yopougon 36 %, Abobo 26 %, Cocody 20 %, Koumassi 18 %. Chaque commune pilote dispose de 2 points relais.

## 2. Résultats de la simulation (3 mois)

| Commune | Ménages | Commerçants | Déclarations | kg validés | FCFA versés | Points | Part point relais | Signalements |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Yopougon | 192 | 80 | 2 160 | 20 159 | 4 857 790 | 139 042 | 76,8 % | 103 |
| Abobo | 117 | 53 | 1 292 | 12 152 | 2 875 295 | 83 484 | 75,5 % | 107 |
| Cocody | 97 | 39 | 1 081 | 10 032 | 2 432 230 | 62 953 | 73,6 % | 98 |
| Koumassi | 94 | 28 | 926 | 6 385 | 1 524 615 | 52 281 | 81,1 % | 112 |
| **Total** | **500** | **200** | **5 459** | **48 728** | **11 689 930** | **337 760** | | **420** |

- **48,7 tonnes** de déchets recyclables collectées et pesées en 3 mois.
- Revenu moyen : **2 126 FCFA/mois** par ménage actif et **17 415 FCFA/mois** par commerçant actif.
- **1 729 demandes de collecte à domicile** sous le seuil Y ont été réorientées vers un point relais.
- **52 tournées** optimisées pour les dépôts sauvages, avec leurs coûts réels (carburant, main d'œuvre, véhicule).

**Hypothèses de comportement**
- 78 % des ménages et 88 % des commerçants inscrits sont actifs.
- Un ménage dépose tous les 7 à 18 jours, un commerçant tous les 4 à 10 jours.
- Le poids pesé vaut 82 à 105 % du poids déclaré : les usagers surestiment légèrement.
- 3 % des déclarations sont rejetées : déchets souillés ou mal triés.

## 3. Barème de rémunération

| Matière | Tarif |
|---|---:|
| Carton | 200 FCFA/kg |
| Plastique | 250 FCFA/kg |
| Aluminium | 300 FCFA/kg |

**Justification**
- Le tarif suit la valeur de revente des matières : aluminium > plastique > carton.
- La rémunération se calcule sur le **poids pesé par l'agent**, au tarif du jour, et non sur le poids déclaré. Cela évite la fraude sur les poids.
- Les tarifs sont modifiables par l'administrateur, avec un historique complet. Une déclaration garde le tarif appliqué au moment de sa validation.

## 4. Seuil Y = 10 kg

**Définition retenue** : poids minimum d'un apport pour avoir droit à une **collecte à domicile**.
En dessous, l'usager est orienté vers un **point relais**, où il gagne des points en plus de sa rémunération.

**Justification économique**
- Un arrêt de collecte à domicile coûte environ **800 FCFA** : 500 FCFA de main d'œuvre et environ 2 km de détour à 150 FCFA/km.
- À 10 kg, ce coût représente **80 FCFA/kg**, soit **32 % du prix moyen de rachat** (250 FCFA/kg). En dessous, la logistique coûte proportionnellement plus cher que ce que vaut le déchet.
- La vue Snowflake `SIM.V_SENSIBILITE_SEUIL_Y` compare Y = 0, 5, 10, 15 et 20 kg : nombre d'arrêts, apports réorientés et coût logistique par kg.

## 5. Points de fidélité et conversion

| Action | Points |
|---|---:|
| Dépôt en point relais | 10 points/kg validé + 20 points de bonus par dépôt |
| Signalement confirmé par un agent | 15 points |

- **Conversion** : 1 point = 1 FCFA, versé en Mobile Money.
- **Minimum** : 500 points par conversion.

**Justification**
- Un dépôt de 5 kg en point relais rapporte 70 points, soit 70 FCFA. C'est bien moins que les 800 FCFA économisés en évitant un arrêt à domicile.
- Le bonus coûte donc moins cher que la collecte qu'il remplace. Il encourage le geste le plus économique : apporter soi-même ses déchets.
- Le minimum de 500 points évite une multitude de petits virements Mobile Money, chacun ayant un coût de traitement.

Toutes ces valeurs sont des paramètres modifiables (admin → Tarifs & paramètres). Les justifications affichées
dans l'application se recalculent automatiquement quand on les change.

## 6. Utilisation de Snowflake

| Fonctionnalité | Utilisation dans EcoAbidjan | Où la voir |
|---|---|---|
| **Données synthétiques avec GENERATOR** | Création des 500 ménages et 200 commerçants répartis par commune, et de 13 semaines de déclarations | `snowflake/06_simulation_generator.sql`, schéma `ECOABIDJAN.SIM` |
| **Tables GEOGRAPHY** | Position des ménages, commerçants, points relais et signalements ; distance au point relais le plus proche, détection des doublons à moins de 50 m | `06_simulation_generator.sql`, `07_geography_and_ai_classify.sql` |
| **Stage pour les photos** | Stage interne chiffré `RAW.PHOTOS_STAGE` | `01_setup.sql` |
| **Cortex AI_COMPLETE** | Analyse des photos de dépôts : matières, volume et poids estimés | `05_cortex_image_analysis.sql` et backend (`AI_PROVIDER=snowflake`) |
| **Cortex AI_CLASSIFY** | Classification multi-étiquettes des matières sur photo, niveau d'urgence d'un signalement | `07_geography_and_ai_classify.sql` |
| **Cortex COMPLETE (chat)** | Rédaction des réponses de l'assistant Eco | backend `services/assistant.py` |
| **Stockage analytique** | Copie des données de l'application et vues du tableau de bord | `02_tables.sql`, `04_analytics_views.sql` |

Depuis l'application (admin → Snowflake), un administrateur peut connecter le compte, lancer le diagnostic,
installer automatiquement les scripts 01, 02, 04 et 06, puis synchroniser les données.
