# EcoAbidjan ♻

Application de gestion et de valorisation des déchets à Abidjan (Côte d'Ivoire).

- **Citoyens** : signalent les dépôts sauvages avec une photo et leur position GPS. L'IA identifie les matières et estime le poids.
- **Ménages et commerçants** : déclarent leurs déchets recyclables (carton, plastique, aluminium) et sont rémunérés selon le poids validé.
- **Points de fidélité** pour les apports en point relais et les signalements confirmés.
- **Agents** : confirment les signalements, pèsent et valident les déclarations, réalisent des tournées optimisées.
- **Administrateurs** : tableau de bord, tarifs (avec historique), paramètres, paiements, synchronisation Snowflake.

## Architecture

| Couche | Technologie | Rôle |
|---|---|---|
| Interface | HTML/CSS/JS responsive, Leaflet (cartes), Chart.js | Espace usager et espace agent/admin |
| Backend | Python, FastAPI, SQLAlchemy | API REST, règles métier, authentification JWT |
| Base opérationnelle | PostgreSQL/PostGIS (production) ou SQLite (local) | Données transactionnelles |
| Analytique et IA | Snowflake + Cortex AI (`AI_COMPLETE` multimodal) | Vues du tableau de bord, analyse des photos |

**Ce qui se fait où**
- *PostgreSQL* : inscriptions, signalements, déclarations, validations, paiements, points, tournées (écritures temps réel).
- *Snowflake* : copie des données (sans e-mail, téléphone ni mot de passe), vues analytiques, analyse d'images par Cortex AI, analyses en lot.

## Démarrage rapide (Windows)

Python 3.11 ou plus récent est nécessaire.

```powershell
python -m venv $env:USERPROFILE\.venvs\ecoabidjan
& $env:USERPROFILE\.venvs\ecoabidjan\Scripts\python.exe -m pip install -r requirements.txt
& $env:USERPROFILE\.venvs\ecoabidjan\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Ouvrir ensuite http://localhost:8000. La documentation de l'API est disponible sur http://localhost:8000/docs.

> L'environnement Python est créé dans un chemin court car Windows refuse de charger certains composants quand le chemin est trop long.

Au premier démarrage, la base est créée et remplie avec le référentiel (13 communes, matières, tarifs, 7 points relais) et 6 mois de données de démonstration (`SEED_DEMO=false` pour les désactiver).

### Comptes de démonstration

Mot de passe commun : `Demo@2026`

| Rôle | E-mail |
|---|---|
| Administrateur | admin@ecoabidjan.ci |
| Agent | agent@ecoabidjan.ci |
| Citoyen | citoyen@ecoabidjan.ci |
| Ménage | menage@ecoabidjan.ci |
| Commerçant | commercant@ecoabidjan.ci |

⚠ À supprimer ou changer avant toute mise en ligne.

### Tests

```powershell
& $env:USERPROFILE\.venvs\ecoabidjan\Scripts\python.exe -m pytest -q tests
```

## Règles métier

- **Tarifs de référence** (modifiables par l'admin, historique conservé) : carton 200, plastique 250, aluminium 300 FCFA/kg.
- **Rémunération** = poids **validé** par l'agent × tarif en vigueur au moment de la validation. Le poids déclaré reste une estimation.
- **Points** : 10 points/kg validé + 20 points de bonus par apport en point relais ; 15 points par signalement confirmé. Tous ces barèmes sont dans la table `parameters`.
- **IA** : l'estimation du poids sur photo est indicative et tracée (fournisseur, modèle, version du prompt, réponse brute, durée). Le tableau de bord mesure son écart avec le poids réellement collecté.
- **Tournées** : itinéraire optimisé (plus proche voisin + 2-opt) depuis un point relais, avec durée et coût estimés (carburant, main d'œuvre, coût fixe), puis saisie des coûts réels.

## Snowflake

1. Dans Snowsight, exécuter dans l'ordre les scripts du dossier [`snowflake/`](snowflake/) :
   - `00_diagnostic.sql` : vérifie la région, l'accès à Cortex et les modèles disponibles. **À faire en premier.**
   - `01_setup.sql` : entrepôt, base `ECOABIDJAN`, schémas `RAW`/`CORE`/`ANALYTICS`, rôle `ECOABIDJAN_APP`, stage des photos.
   - `02_tables.sql` : tables du schéma `CORE`.
   - `03_reference_data.sql` : matières et tarifs initiaux (facultatif).
   - `04_analytics_views.sql` : vues du tableau de bord.
   - `05_cortex_image_analysis.sql` : analyse des photos en lot avec Cortex.
2. Installer le connecteur : `pip install -r requirements-optional.txt`
3. Copier `.env.example` en `.env` et renseigner `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (ou une clé RSA).
4. Dans l'application (admin → Snowflake) : **Lancer le diagnostic**, puis **Synchroniser les données**.
5. Pour analyser les photos avec Cortex : `AI_PROVIDER=snowflake` dans `.env`. En cas d'erreur Cortex, l'application bascule sur l'estimation locale et note l'erreur.

**À vérifier dans ton compte** (le diagnostic le fait pour toi) :
- le modèle multimodal (`claude-3-5-sonnet` par défaut, variable `CORTEX_VISION_MODEL`) est disponible dans ta région, sinon il faut activer `CORTEX_ENABLED_CROSS_REGION` ;
- ton rôle dispose de `SNOWFLAKE.CORTEX_USER` ;
- les comptes d'essai peuvent limiter certaines fonctions Cortex.

## PostgreSQL / PostGIS (production)

```
DATABASE_URL=postgresql+psycopg://ecoabidjan:motdepasse@localhost:5432/ecoabidjan
```

Démarrer l'application une fois (création des tables), puis exécuter [`postgres/01_postgis.sql`](postgres/01_postgis.sql) pour les colonnes géographiques et les index spatiaux.

## Structure

```
backend/app/
  main.py            point d'entrée FastAPI
  models.py          modèle de données (16 tables)
  routers/           public (auth, référentiels), citizen (usagers), admin (agents/admin)
  services/          business (tarifs, rémunération, points), ai (analyse photo),
                     routing (tournées), snowflake_client (diagnostic, synchronisation)
  seed.py            référentiel et données de démonstration
frontend/            interface web (index.html, app.js, styles.css)
snowflake/           scripts SQL Snowflake
postgres/            script PostGIS
tests/               tests automatisés (pytest)
```

## Avant une mise en production

- Remplacer `SECRET_KEY` par une longue chaîne aléatoire et supprimer les comptes de démo.
- Servir l'application en HTTPS (la géolocalisation du navigateur l'exige hors `localhost`).
- Brancher un vrai paiement Mobile Money (aujourd'hui, l'admin saisit la référence à la main).
- Stocker les photos sur un stockage objet (S3, Azure Blob…) plutôt que sur le disque du serveur.
