# EcoAbidjan ♻

Application de gestion et de valorisation des déchets à Abidjan (Côte d'Ivoire).

- **Citoyens** : signalent les dépôts sauvages avec une photo et leur position GPS. L'IA identifie les matières et estime le poids.
- **Ménages et commerçants** : déclarent leurs déchets recyclables (carton, plastique, aluminium) et sont rémunérés selon le poids validé.
- **Points de fidélité** pour les apports en point relais et les signalements confirmés.
- **Agents** : confirment les signalements, pèsent et valident les déclarations, réalisent des tournées optimisées.
- **Administrateurs** : tableau de bord, tarifs (avec historique), paramètres, paiements, synchronisation Snowflake.

## Projet pilote (hackathon)

4 communes (Yopougon, Abobo, Cocody, Koumassi), **500 ménages, 200 commerçants** et 150 citoyens simulés sur 3 mois : 48,7 t recyclées, 11,7 M FCFA versés. Seuil Y = 10 kg, barème et conversion des points sont définis et justifiés dans [docs/regles_et_simulation.md](docs/regles_et_simulation.md). La simulation existe aussi dans Snowflake (GENERATOR + GEOGRAPHY) : [snowflake/06_simulation_generator.sql](snowflake/06_simulation_generator.sql).

Relancer la simulation locale : `python -m backend.app.simulate`

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

## Assistant IA « Eco »

Un assistant de chat est disponible sur toutes les pages (bouton 💬), pour les visiteurs comme pour les usagers, agents et administrateurs.

- **Personnalisé** : il répond à partir des vraies données de l'utilisateur (points, gains payés et en attente, statut des déclarations et signalements) et, pour les agents/admins, des indicateurs du moment (déclarations à valider, paiements en attente, communes les plus touchées).
- **Calculs fiables** : « J'ai 5 kg de plastique et 20 canettes » → estimation au tarif du jour et points gagnés en point relais. Les chiffres sont calculés par l'application, jamais inventés par le modèle.
- **Points relais les plus proches** grâce à la géolocalisation.
- **Voix** : dictée au micro 🎤 et lecture des réponses à voix haute 🔊 (navigateurs compatibles), pour les personnes qui lisent difficilement.
- **Liens d'action** vers le bon écran (Déclarer, Signaler, Portefeuille, Validations…).
- **Moteur hybride** : quand Snowflake est connecté, les réponses sont rédigées par **Snowflake Cortex AI** (`SNOWFLAKE.CORTEX.COMPLETE`, modèle `CORTEX_CHAT_MODEL`) avec l'historique de la conversation. Sinon, ou en cas d'erreur, un moteur local répond : l'assistant fonctionne toujours, même hors ligne. `ASSISTANT_PROVIDER=local` force le moteur local.
- **Traçabilité** : chaque échange est enregistré (intention détectée, moteur, modèle, latence) et répliqué dans Snowflake (`CORE.CHAT_MESSAGES`, vue `ANALYTICS.V_ASSISTANT_USAGE`) pour savoir ce que demandent les habitants.

## Snowflake

Snowflake est intégré **côté serveur uniquement** : rien ne se configure dans l'interface.
Connexion par **paire de clés RSA** (pas de mot de passe, compatible avec la double authentification des comptes d'essai).

```powershell
pip install -r requirements-optional.txt
# 1. Configurer la connexion (cree la cle dans data/, ecrit .env, affiche la commande ALTER USER)
python -m backend.app.snowflake_cli init --account ORGNAME-ACCOUNTNAME --user MON_USER --cortex
# 2. Executer UNE FOIS dans Snowsight la commande ALTER USER affichee
# 3. Diagnostic + installation (scripts 01, 02, 04, 06) + synchronisation + test de Cortex
python -m backend.app.snowflake_cli all
```

Ensuite, au démarrage du serveur :
- **Synchronisation automatique** des données vers `ECOABIDJAN.CORE` toutes les `SNOWFLAKE_SYNC_MINUTES` (30 par défaut).
- **Analyse des photos** par Cortex `AI_COMPLETE` (`AI_PROVIDER=snowflake`), avec repli local automatique en cas d'erreur.
- **Assistant Eco** rédigé par Cortex `COMPLETE`.

Autres commandes : `check`, `setup`, `sync`, `test-ai`. Les scripts du dossier [`snowflake/`](snowflake/) peuvent aussi être exécutés à la main dans Snowsight :
- `00` diagnostic
- `01` installation
- `02` tables
- `03` référentiel
- `04` vues
- `05` analyse des photos par `AI_COMPLETE`
- `06` simulation `GENERATOR` + `GEOGRAPHY`
- `07` `GEOGRAPHY` + `AI_CLASSIFY`

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
