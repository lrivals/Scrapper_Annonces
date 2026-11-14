# Sprint 2 — Interface de navigation & Vérification des liens

**Objectif initial** : API REST + Dashboard visuel.
**Objectif livré** : Interface web légère de navigation/gestion des annonces + vérification fiable des liens expirés.

**Statut** : ✅ Terminé (périmètre révisé) — 4/4 tâches livrées, 4 reportées au Sprint 2-bis

**Date de clôture** : 2026-03-02

---

## Ce qui a été livré

### 2.1 Interface web Flask — Navigation des annonces ✅

**Problème** : Les annonces ne sont consultables qu'à travers des exports Markdown/CSV statiques.

**Actions** :
- Créer `ui.py` — application Flask avec template HTML embarqué
- Route `GET /` avec filtres par query params :
  - `site` — dropdown SeLoger / LeBonCoin / Tous
  - `status` — active / expired / Tous
  - `prix_min`, `prix_max` — fourchette en euros
  - `sort` — prix, distance, date d'ajout, site
  - `order` — asc / desc
- Table avec colonnes : `#` · Site (badge coloré) · Titre (lien cliquable) · Prix (vert/orange/rouge) · Distance km · Lieu · Date ajout · Statut
- URLs bookmarkables (tous les filtres dans les query params)
- Ouverture automatique du navigateur au démarrage (`webbrowser.open`)
- Option CLI `--ui` et `--port` dans `main.py`
- `init_db()` appelé au démarrage pour garantir les migrations

**Fichiers** : `ui.py`, modification `main.py`

**Critère de validation** : `python main.py --ui` ouvre le navigateur sur `http://127.0.0.1:5000` et affiche les annonces avec filtres fonctionnels.

**Résultat** : ✅ 196 annonces affichées, filtres et tri opérationnels, badge site coloré, code couleur prix.

---

### 2.2 Suppression manuelle des annonces ✅

**Problème** : Pas de moyen de retirer manuellement une annonce obsolète depuis l'interface.

**Actions** :
- Route `POST /delete` dans `ui.py`
- Bouton ✕ par ligne dans la table (confirm natif navigateur)
- Message flash (vert/rouge) après suppression
- Retour vers la vue filtrée courante après suppression (`back_url` préservé)
- Helper `_add_flash()` pour injecter les params flash dans l'URL de redirection

**Fichiers** : `ui.py`

**Critère de validation** : Cliquer ✕ sur une ligne, confirmer → annonce supprimée de la DB, message vert affiché.

**Résultat** : ✅ Suppression immédiate, vue filtrée préservée, flash messages fonctionnels.

---

### 2.3 Vérificateur de liens Playwright ✅

**Problème** : `--purge` utilise `requests.head()` (sans rendu JS) → marque toutes les annonces SeLoger/LeBonCoin comme expirées car les SPAs bloquent les requêtes brutes. 196 annonces incorrectement marquées `expired`.

**Actions** :
- Nouvelle fonction `check_links_playwright(limit)` dans `storage/cleaner.py`
- Navigateur Chromium headless via Playwright (pas de profil persistant, pas de CDP)
- Délai aléatoire **3–5 secondes** après chargement (`wait_until="domcontentloaded"` + `wait_for_timeout`)
- Détection de messages d'erreur dans le HTML rendu (liste `_EXPIRED_PATTERNS`) :
  - SeLoger : `"cette annonce a déjà été supprimée"`, `"annonce supprimée"`, `"il n'y a plus cette annonce"`
  - LeBonCoin : `"cette annonce a été désactivée"`, `"cette annonce n'est plus en ligne"`, `"cette annonce n'existe plus"`
  - Génériques : `"page introuvable"`, `"404 not found"`
- Marque `status = 'expired'` en base si pattern trouvé
- Gestion d'erreurs par annonce (timeout, réseau) sans interrompre la boucle
- Option CLI `--check-links` et `--limit` dans `main.py`
- `init_db()` appelé avant la vérification

**Fichiers** : `storage/cleaner.py`, modification `main.py`

**Critère de validation** : `python main.py --check-links --limit 10` charge 10 annonces dans un vrai navigateur, détecte les supprimées, et les marque expired.

**Résultat** : ✅ Fonctionne. Correction appliquée : statuts remis à `active` après la fausse purge de `--purge`.

---

### 2.4 Refactorisation des imports (lazy loading) ✅

**Problème** : `python main.py --ui` échoue avec `ModuleNotFoundError: No module named 'playwright'` car tous les scrapers sont importés au niveau module, même quand Playwright n'est pas nécessaire.

**Actions** :
- Déplacer les imports scrapers/filtres/storage dans `main()`, après les early returns `--ui` et `--check-links`
- Seuls `argparse`, `datetime` et `utils.logger` restent au niveau module
- `SCRAPER_MAP` devient `scraper_map` (variable locale dans `main()`)

**Fichiers** : `main.py`

**Critère de validation** : `python main.py --ui` fonctionne sans playwright installé dans l'environnement courant.

**Résultat** : ✅ Imports différés, chaque mode ne charge que ses dépendances.

---

## Sprint 2-bis — API JSON, tendances, Docker (livré le 2026-11-14)

**Statut** : ✅ Terminé — validé sur la base réelle, profil **Blagnac**.

> Recadré le 2026-11-14 : l'UI Flask a été refaite depuis (package `ui/`, CSRF, carte Leaflet, Critères,
> Poids). On ne la remplace donc pas par FastAPI + Streamlit : l'API JSON est un blueprint de la même
> application, et la carte Folium n'a plus d'objet.

| # | Tâche | Statut | Livrable |
|---|-------|--------|----------|
| 2-bis.1 | API REST en lecture | ✅ | `ui/api.py`, monté sur `/api/v1` : `profiles`, `annonces` (filtres et tris de la liste), `annonces/<id>` (+ historique des prix), `runs`, `stats`, `stats/history` |
| 2-bis.2 | Tableau de bord « Tendances » | ✅ | Page `/tendances` (lien depuis la liste) : nouvelles par jour et par site, loyer CC médian (jour + 7 jours glissants), stock à chaque run ; Chart.js 4.4.1 épinglé (cdnjs) |
| 2-bis.3 | Configuration dynamique | ✅ | Couvert par les pages « Critères » (15.5) et « Poids du score » (15.6) — rien à coder |
| 2-bis.4 | Historique & tendances | ✅ | `storage/trends.py` : séries par jour (depuis `annonce_profiles.matched_at`, tout l'historique) et par run (`run_stats`, Sprint 5.0) |
| 2-bis.5 | Docker (UI + API seulement) | ✅ | `Dockerfile`, `docker-compose.yml`, `.dockerignore` ; port publié sur 127.0.0.1 ; le scraping reste sur la machine |
| 2-bis.6 | Tests API | ✅ | `tests/test_api.py` (15 tests : accès, filtres, pagination, 404, jeton, séries, page) |

### API

```bash
curl "http://127.0.0.1:5000/api/v1/annonces?profile=blagnac&prix_max=750&sort=score&limit=20"
curl "http://127.0.0.1:5000/api/v1/annonces/1035?profile=blagnac"     # + price_history
curl "http://127.0.0.1:5000/api/v1/stats?profile=blagnac"
curl "http://127.0.0.1:5000/api/v1/stats/history?profile=blagnac&days=90"
```

- Paramètres de `annonces` : ceux de la liste (`site`, `status`, `prix_min`, `prix_max`, `dups`, `fb`,
  `excl`, `sort` = score|price|distance|created_at|site, `order`) + `limit` (≤ 500) et `offset`.
- Champs publiés : liste blanche (`LIST_FIELDS` / `DETAIL_FIELDS`) ; empreintes, erreurs et données
  LLM brutes restent privées. Colonnes JSON décodées, booléens en `true`/`false`.
- **Accès** : libre depuis la machine (127.0.0.1). Sinon `Authorization: Bearer <API_TOKEN>` (`.env`) ;
  sans `API_TOKEN`, refus. Un jeton faux est refusé même en local.
- Lecture seule : un POST ou DELETE est refusé.

### Docker

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --build   # UI_PORT=5058 si 5000 est pris
```

- L'image contient le code, jamais `.env`, `data/`, `logs/`, `reports/` ni `Docrech/` (`.dockerignore`).
- `data/` est monté en lecture-écriture : SQLite en WAL écrit ses fichiers `-shm` / `-wal`, et l'UI
  enregistre ⭐ / 👎 / masquage. Le conteneur tourne avec l'UID de l'hôte : les fichiers gardent leur propriétaire.
- Le bouton « Lancer le scraping » ne fonctionne pas dans le conteneur (pas de Chrome) : le timer
  systemd de la machine continue de scraper ; l'UI du conteneur lit la même base.
- Vu du conteneur, l'hôte n'est pas « local » : l'API y exige `API_TOKEN` (dans `.env`).

### Validation (2026-11-14)

- `/tendances?profile=blagnac` rendu dans Chromium sans erreur JavaScript : 381 annonces, 817 € CC médian,
  15,0 €/m², 47 / 279 nouvelles (24 h / 7 j). Les pics du 04/11 et du 13/11 sont les premières recherches
  du profil et le rattrapage du 13/11 (Sprint 16), pas le marché.
- API sur la base réelle : 200 en local ; 403 depuis une autre adresse sans jeton configuré.
- Conteneur : pages 200 ; API 401 sans jeton ou avec un mauvais, 200 avec `API_TOKEN`.

---

## Résumé

| # | Tâche | Priorité | Effort | Statut |
|---|-------|----------|--------|--------|
| 2.1 | Interface Flask navigation | Haute | M | ✅ |
| 2.2 | Suppression manuelle (UI) | Haute | S | ✅ |
| 2.3 | Vérificateur liens Playwright | Haute | M | ✅ |
| 2.4 | Refactorisation imports lazy | Haute | S | ✅ |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure après Sprint 2

```
toulouse_rent_scraper/
├── ui.py                   # NOUVEAU — Flask app + template HTML embarqué
├── main.py                 # Modifié — --ui, --port, --check-links, --limit, imports lazy
├── storage/
│   ├── sqlite.py
│   └── cleaner.py          # Modifié — check_links_playwright(), _EXPIRED_PATTERNS
├── requirements.txt        # Modifié — flask>=3.0.0 ajouté
└── ...
```

---

## Usage

```bash
# Interface de navigation
python main.py --ui
python main.py --ui --port 8080

# Vérification des liens (navigateur headless)
python main.py --check-links              # toutes les annonces actives
python main.py --check-links --limit 20   # limité à 20

# NE PAS UTILISER --purge sur SeLoger/LeBonCoin (faux positifs garantis)
```

---

## Décisions techniques prises

| Décision | Contexte |
|----------|----------|
| Flask plutôt que FastAPI/Streamlit | Périmètre "petite interface" — 1 fichier, 0 dépendance lourde |
| Template HTML embarqué dans `ui.py` | Pas de dossier `templates/`, tout en 1 fichier |
| Filtres via `GET` (pas JS) | URLs bookmarkables, no-JS, simple |
| Flash via query params (pas session) | Stateless, pas de secret Flask nécessaire |
| Playwright headless pour link check | Les SPAs ne répondent pas aux requêtes `requests.head()` |
| `--purge` déprécié pour SPAs | Marqué avec avertissement dans `cleaner.py` |
