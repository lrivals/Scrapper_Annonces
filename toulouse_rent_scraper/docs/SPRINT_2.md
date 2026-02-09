# Sprint 2 — API REST & Dashboard

**Objectif** : Offrir une interface visuelle et une API pour consulter et piloter le scraper depuis un navigateur.

**Durée estimée** : 2 semaines

**Prérequis** : Sprint 1 terminé (export, notifications, données propres).

---

## Tâches

### 2.1 API REST FastAPI (Priorité: Haute | Effort: L)

**Problème** : Aucun moyen d'interroger les données programmatiquement ou de lancer le scraper à distance.

**Actions** :
- Installer FastAPI + Uvicorn
- Créer `api/` avec la structure suivante :
  - `api/main.py` — app FastAPI, configuration CORS
  - `api/routes/annonces.py` — endpoints annonces
  - `api/routes/scraper.py` — endpoints pilotage scraper
  - `api/schemas.py` — modèles Pydantic (AnnonceResponse, StatsResponse, etc.)
- Endpoints à implémenter :
  - `GET /api/annonces` — liste paginée avec filtres query params :
    - `?site=LeBonCoin` — filtre par source
    - `?prix_max=450` — filtre par prix
    - `?distance_max=5` — filtre par distance ENAC
    - `?page=1&limit=20` — pagination
    - `?sort=price&order=asc` — tri
  - `GET /api/annonces/nouvelles` — annonces des dernières 24h
  - `GET /api/annonces/{id}` — détail d'une annonce
  - `GET /api/stats` — statistiques globales :
    - Nombre total d'annonces
    - Prix moyen / médian
    - Répartition par site
    - Répartition par tranche de distance
  - `POST /api/scrape` — lance un scraping en arrière-plan (async)
    - Body : `{"sites": ["seloger", "leboncoin"]}`
    - Retourne un `job_id` pour suivre l'avancement
  - `GET /api/scrape/{job_id}` — statut du job de scraping
- Point d'entrée : `uvicorn api.main:app --reload --port 8000`

**Critère de validation** : `GET /api/annonces?prix_max=400&distance_max=3` retourne les annonces filtrées en JSON. La doc Swagger est accessible sur `/docs`.

---

### 2.2 Dashboard Streamlit (Priorité: Haute | Effort: L)

**Problème** : Les rapports Markdown sont utiles mais pas interactifs. Pas de visualisation géographique.

**Actions** :
- Installer Streamlit + Folium + Plotly
- Créer `dashboard/app.py` avec les pages suivantes :

**Page 1 — Tableau de bord** :
- KPIs en haut : nombre total d'annonces, prix moyen, nouvelles aujourd'hui
- Tableau filtrable et triable (prix, distance, site, date)
- Bouton "Lancer le scraping" (appel API `POST /api/scrape`)

**Page 2 — Carte interactive** :
- Carte Folium centrée sur l'ENAC
- Marqueur ENAC (rouge, fixe)
- Marqueurs annonces (couleur par tranche de prix) :
  - Vert : < 350€
  - Orange : 350-450€
  - Rouge : > 450€
- Popup au clic : titre, prix, distance, lien vers l'annonce
- Cercle de rayon `MAX_DISTANCE_KM` autour de l'ENAC

**Page 3 — Tendances** :
- Graphique d'évolution du nombre d'annonces par jour
- Graphique du prix moyen par semaine
- Répartition par quartier (bar chart)

- Point d'entrée : `streamlit run dashboard/app.py`

**Critère de validation** : Le dashboard affiche les annonces sur une carte avec filtres interactifs. Les graphiques de tendance montrent l'évolution.

---

### 2.3 Configuration dynamique (Priorité: Moyenne | Effort: M)

**Problème** : Modifier les critères de recherche nécessite d'éditer `config.py` manuellement.

**Actions** :
- Créer une table `config` en SQLite :
  ```sql
  CREATE TABLE config (
      key TEXT PRIMARY KEY,
      value TEXT,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )
  ```
- Stocker les paramètres modifiables : `max_rent`, `max_distance_km`, `target_city`, `enac_lat`, `enac_lng`
- `config.py` lit d'abord la DB, fallback sur les constantes codées en dur
- Ajouter un endpoint API `PUT /api/config` et `GET /api/config`
- Page Settings dans le dashboard Streamlit pour modifier les critères
- Migration DB automatique (même pattern que `created_at`)

**Critère de validation** : Modifier le budget max via le dashboard change effectivement le filtrage au prochain run.

---

### 2.4 Historique & tendances (Priorité: Moyenne | Effort: M)

**Problème** : Pas de visibilité sur l'évolution du marché locatif dans le temps.

**Actions** :
- Créer une table `stats_history` :
  ```sql
  CREATE TABLE stats_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date DATE UNIQUE,
      total_annonces INTEGER,
      new_annonces INTEGER,
      avg_price REAL,
      median_price REAL,
      min_price INTEGER,
      max_price INTEGER
  )
  ```
- Alimenter automatiquement après chaque run (dans `main.py`)
- Endpoint API `GET /api/stats/history?days=30`
- Graphiques Plotly dans le dashboard (page Tendances)
- Export CSV de l'historique

**Critère de validation** : Après 1 semaine de runs quotidiens, le graphique montre l'évolution du prix moyen.

---

### 2.5 Dockerisation (Priorité: Moyenne | Effort: M)

**Problème** : Installation manuelle (Python, venv, Playwright, Chrome). Pas portable.

**Actions** :
- Créer `Dockerfile` :
  - Base : `python:3.12-slim`
  - Installation de Playwright + Chromium
  - Copie du code + `pip install -r requirements.txt`
- Créer `docker-compose.yml` avec 3 services :
  - `scraper` — exécution cron (toutes les 8h)
  - `api` — FastAPI sur port 8000
  - `dashboard` — Streamlit sur port 8501
- Volume partagé pour la DB SQLite (`./data:/app/data`)
- Fichier `.env.example` avec les variables nécessaires
- Documentation dans le README

**Critère de validation** : `docker compose up` lance les 3 services. Le dashboard est accessible sur `localhost:8501`.

---

### 2.6 Tests API (Priorité: Moyenne | Effort: S)

**Actions** :
- Tests d'intégration FastAPI avec `TestClient` :
  - Test pagination et filtres sur `GET /api/annonces`
  - Test réponse `GET /api/stats`
  - Test lancement scraping `POST /api/scrape`
  - Test configuration `PUT /api/config`
- Fixtures : DB en mémoire avec données de test
- CI : ajout d'un script `scripts/run_tests.sh` qui lance tous les tests

**Critère de validation** : `pytest tests/ -v` couvre les endpoints API, tout vert.

---

## Résumé

| # | Tâche | Priorité | Effort | Dépendance |
|---|-------|----------|--------|------------|
| 2.1 | API REST FastAPI | Haute | L | Sprint 1 |
| 2.2 | Dashboard Streamlit | Haute | L | 2.1 (API) |
| 2.3 | Configuration dynamique | Moyenne | M | 2.1 |
| 2.4 | Historique & tendances | Moyenne | M | 2.1, 2.2 |
| 2.5 | Dockerisation | Moyenne | M | 2.1, 2.2 |
| 2.6 | Tests API | Moyenne | S | 2.1 |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure cible après Sprint 2

```
toulouse_rent_scraper/
├── api/                    # NOUVEAU
│   ├── __init__.py
│   ├── main.py             # App FastAPI
│   ├── schemas.py          # Modèles Pydantic
│   └── routes/
│       ├── annonces.py
│       └── scraper.py
│
├── dashboard/              # NOUVEAU
│   └── app.py              # App Streamlit
│
├── scrapers/
├── filters/
├── storage/
├── reporting/
├── notifications/
├── geo/
├── utils/
├── tests/
├── docs/
│
├── Dockerfile              # NOUVEAU
├── docker-compose.yml      # NOUVEAU
├── .env.example            # NOUVEAU
└── config.py
```

---

## Stack technique

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| API | FastAPI | Async natif, docs auto Swagger, Pydantic |
| Dashboard | Streamlit | Rapide à prototyper, widgets interactifs, carte Folium intégrée |
| Graphiques | Plotly | Interactifs, compatible Streamlit |
| Carte | Folium | OpenStreetMap, marqueurs personnalisés, léger |
| Conteneurs | Docker Compose | Orchestration simple, 3 services isolés |
