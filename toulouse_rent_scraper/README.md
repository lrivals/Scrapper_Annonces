# Toulouse Rent Scraper

Scraper d'annonces de location à Toulouse, avec filtrage automatique par prix et par distance à une cible, pour plusieurs **profils de recherche**.

---

## Objectif

Rechercher automatiquement des annonces de location, avec lien direct vers l'annonce, pour chaque profil défini dans `config.SEARCH_PROFILES` :

| Profil | Cible | Budget | Rayon | Pièces | Recherches |
|--------|-------|--------|-------|--------|------------|
| `enac` | ENAC — 7 av. Édouard Belin, Toulouse | 50 – 500 € | 10 km | toutes | URLs construites (studio, Toulouse) |
| `blagnac` | 14 Pl. Marcel Dassault, Blagnac | aucun filtre (cible 600 € pour le score) | 8 km | aucun filtre | URLs copiées du site + warm-up (voir ci-dessous) |

Pour `blagnac`, le filtrage se fait surtout dans les recherches elles-mêmes : appartement (et maison
sur LeBonCoin) avec balcon/terrasse/jardin, Toulouse + Blagnac, ≤ 3 pièces sur SeLoger. Côté
scraper, seul le rayon de 8 km est appliqué.

---

## Installation

### Prérequis

- Python 3.8+
- Linux (testé sur Ubuntu/Debian)

### 1. Cloner le projet

```bash
cd toulouse_rent_scraper
```

### 2. Créer un environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install -r requirements.txt        # exécution
pip install -r requirements-dev.txt    # + outils de test
```

### 4. Navigateurs

- **Scraping et enrichissement** : un vrai Chrome/Chromium installé sur la machine
  (`google-chrome` ou `chromium` dans le PATH, sinon renseigner `CHROME_BINARY` dans `config.py`).
  Il est piloté via CDP avec un profil persistant (`data/browser_profile/`) pour passer l'anti-bot DataDome.
- **Vérification des liens** (`check-links`) : le Chromium de Playwright, en headless :

```bash
playwright install chromium
```

---

## Utilisation

### Lancer le scraper

```bash
python main.py scrape        # ou simplement : python main.py
```

Le script va :

1. Lancer une recherche par profil (ENAC, Blagnac…) et par site (SeLoger, LeBonCoin via navigateur ;
   Bien'ici via son API JSON, sans navigateur)
2. Filtrer les annonces par budget, nombre de pièces et distance à la cible de chaque profil
   (un critère absent du profil n'est pas filtré)
3. Stocker les nouvelles annonces dans `data/annonces.sqlite`
4. Générer des rapports Markdown dans `reports/`
5. Générer des logs dans `logs/`

### Commandes

```bash
python main.py scrape                              # tous les sites, tous les profils
python main.py scrape --site leboncoin             # un site (répétable) : seloger, leboncoin, bienici
python main.py scrape --profile blagnac            # un profil (répétable)
python main.py scrape --enrich --limit 20          # + enrichissement des nouvelles annonces
python main.py scrape --export csv                 # + export CSV (ou json)
python main.py enrich [--site seloger] [--limit 20]  # enrichir les annonces en attente
python main.py check-links [--limit 50]            # vérifier les liens (Chromium headless)
python main.py purge                               # vérification HEAD (peu fiable sur SeLoger/LBC)
python main.py export csv|json                     # export des annonces actives
python main.py rescore                             # recalculer les scores (après un changement de poids)
python main.py weights [--apply|--reset]           # poids du score appris de vos ⭐ / 📞 / 👎
python main.py dedupe                              # doublons inter-sites par empreinte de la 1re photo
python main.py dedupe --recheck [--apply]          # revérifier les doublons déjà rattachés (règles actuelles)
python main.py notify-test                         # vérifier la configuration des notifications
python main.py quality [--days 7]                  # taux de remplissage des champs par site (santé de l’extraction)
python main.py analyze [--limit 20]                # analyse LLM des nouvelles descriptions (une lecture par texte) — voir SPRINT_15
python main.py analyze --stats                     # registre des lectures LLM (appels, jetons), sans appel
python main.py analyze --retry-errors              # relancer une fois les analyses en erreur
python main.py scrape --unattended                 # mode planifié (captcha notifié, sites bloqués sautés)
python main.py ui [--port 8080] [--no-browser]     # interface web
```

L'ancienne syntaxe (`--seloger`, `--leboncoin`, `--ui`, `--check-links`…) reste acceptée, avec un avertissement indiquant la commande équivalente.

### Interface Web

```bash
python main.py ui        # ou : python -m ui
```

Ouvre `http://localhost:5000` — interface responsive pour :

- Basculer entre les profils (onglets ENAC / Blagnac)
- Trier par **score d'intérêt** (défaut), prix, distance au profil ou date ; filtrer (site, statut, prix, doublons)
- Voir l'évolution du prix (↓ 30 € depuis la première détection)
- Masquer / restaurer une annonce, vue carte, export d'un dossier de candidature
- Lancer un scraping (sortie dans `logs/ui_scraping.log`, dernière ligne affichée) — refusé si un run
  du timer est déjà en cours (verrou partagé)

### Score d'intérêt

Chaque annonce reçoit, pour chaque profil, un score sur 100 (pastille ★ dans l'interface, détail au survol) :

| Critère | Poids | Calcul |
|---|---|---|
| Loyer charges comprises | 35 | 1 au loyer cible du profil (`target_rent_eur`), 0 au budget max (ou à 1,5× la cible si pas de plafond) |
| Distance | 30 | 1 sur la cible, 0 en limite de rayon |
| €/m² | 15 | comparé à la médiane des annonces du profil |
| Meublé | 10 | oui = 1, non = 0 |
| DPE | 10 | A–C = 1, D = 0.6, E = 0.3, F–G = 0 |

Un critère inconnu (annonce pas encore enrichie) vaut 0.5 : il ne pénalise pas. Poids réglables via
`SCORE_WEIGHTS` dans `config.py`, puis `python main.py rescore`.

### Retours et poids appris

Chaque carte a trois boutons : ⭐ favori, 📞 contacté, 👎 pas intéressé (par profil ; 👎 retire
l'annonce de la liste par défaut). Après ~30 retours (dont 5 👎), la page « Poids du score » (ou
`python main.py weights`) propose des poids estimés par régression logistique, à côté des poids
actuels ; ils ne s'appliquent qu'après confirmation (`data/score_weights.json`). Un favori qui
baisse de prix ou disparaît du site est toujours notifié.

### Critères éliminatoires

Distincts du score : `requirements=Requirements(...)` dans le profil (`config.py`), par exemple
`Requirements(apl_required=True, no_ground_floor=True, min_surface_m2=18, available_before="2027-01-15")`.
Une annonce qui en viole un est **exclue du profil** : masquée par défaut dans l'interface (filtre
« Critères » pour les revoir, motif ⛔ sur la carte), absente des notifications et des rapports.
Une information inconnue n'exclut jamais. Recalculé à chaque `rescore` : rien n'est perdu en
modifiant un critère. Critères : `available_before`, `apl_required`, `no_ground_floor`,
`min_surface_m2`, `furnished`, `no_colocation`, `excluded_lease_types`, `max_dpe`.

### Notifications

Nouvelles annonces et baisses de loyer (≥ 20 €) au-dessus du score minimal (`NOTIFY_MIN_SCORE`, 55)
envoyées sur le téléphone ; récapitulatif unique au-delà de 3 annonces par profil. Un captcha à
résoudre est aussi signalé.

1. Installer l'appli **ntfy** (Android / iOS) et s'abonner à un topic long et aléatoire.
2. `cp .env.example .env` puis renseigner `NOTIFY_BACKEND=ntfy` et `NTFY_TOPIC=…` (ou Telegram).
3. `python main.py notify-test`

Les actions (masquer, vider la base, lancer le scraping) sont protégées par un jeton CSRF ;
« Vider la BD » demande de taper `VIDER`.

### Consulter les résultats

Après chaque exécution, des rapports sont générés dans `reports/<profil>/` :

- `nouvelles_annonces.md` — Les annonces ajoutées au profil lors de cette exécution
- `toutes_les_annonces.md` — Tableau complet des annonces du profil
- `annonces_detaillees.md` — Annonces enrichies (surface, DPE…)

Requête directe sur la base :

```bash
sqlite3 data/annonces.sqlite "SELECT a.title, a.price, ap.distance_km, a.url FROM annonces a JOIN annonce_profiles ap ON ap.annonce_id = a.id WHERE ap.profile = 'blagnac' ORDER BY ap.distance_km;"
```

---

## Tests

Lancer les tests unitaires :

```bash
pytest tests/ -v
```

Avec couverture :

```bash
pytest tests/ --cov=. --cov-report=html
```

---

## Structure du projet

```text
toulouse_rent_scraper/
├── config.py              # Configuration globale (profils de recherche, Chrome, délais)
├── main.py                # CLI (sous-commandes)
├── pipeline.py            # Recherches profil × site → filtre → stockage → score → notifications → rapports
├── scoring.py             # Score d'intérêt 0–100 par profil
├── requirements.txt       # Dépendances d'exécution (+ requirements-dev.txt)
│
├── ui/                    # Interface web Flask
│   ├── __init__.py        # create_app(), run_ui()
│   ├── routes.py          # Vues (sans SQL)
│   ├── security.py        # CSRF, redirections sûres
│   ├── export.py          # Dossier de candidature Markdown
│   ├── templates/index.html
│   └── static/            # app.css, app.js
│
├── scrapers/              # Scrapers par site
│   ├── __init__.py        # Registre (import paresseux, sans Playwright)
│   ├── browser.py         # Session Chrome partagée (profil persistant + CDP)
│   ├── antibot.py         # Détection / attente des challenges DataDome
│   ├── base.py            # Classe abstraite (navigation, pagination)
│   ├── seloger.py
│   ├── leboncoin.py
│   ├── enricher.py        # Enrichissement (page de détail)
│   └── detail_extractors/
│
├── filters/               # Filtres métier
│   └── price_and_distance.py
│
├── storage/               # Stockage SQLite
│   ├── sqlite.py          # Connexion, écritures (annonces, profils, historique de prix)
│   ├── migrations.py      # Schéma versionné (PRAGMA user_version)
│   ├── queries.py         # Lectures de l'interface web
│   └── cleaner.py         # Vérification des liens expirés
│
├── notify/                # Notifications (ntfy.sh, Telegram) + construction des messages
│
├── deploy/                # Unités systemd (service + timer)
│
├── reporting/             # Génération de rapports
│   ├── generator.py       # Rapports Markdown
│   └── exporter.py        # Export CSV/JSON
│
├── geo/                   # Géolocalisation
│   └── distance.py        # Géocodage Nominatim (cache) + distances
│
├── utils/                 # Utilitaires
│   ├── logger.py          # Logging rotatif
│   ├── validation.py      # Validation des données
│   ├── lock.py            # Verrou inter-processus (un seul run à la fois)
│   └── retry.py           # Retry avec backoff exponentiel
│
├── scripts/
│   ├── repair_data.py     # Réparation des données (Sprint 11)
│   └── debug/             # Capture HTML des cartes (diagnostic des sélecteurs)
│
├── tests/                 # Tests unitaires — passent sans Playwright ni Chrome
│
├── docs/                  # Documentation des sprints
│   ├── ROADMAP.md
│   ├── SPRINT_1.md
│   └── ...
│
├── reports/               # Rapports générés (gitignored)
│   ├── enac/              # un dossier par profil
│   └── blagnac/
│
├── data/                  # Données générées (gitignored)
│   ├── annonces.sqlite
│   └── browser_profile/   # Profil Chrome persistant (anti-bot)
│
└── logs/                  # Logs d'exécution
    └── main.log
```

---

## Configuration

Modifiez `config.py` pour ajuster :

- `SEARCH_PROFILES` : profils de recherche (cible, budget, rayon, pièces, URLs LeBonCoin/SeLoger/Bien'ici,
  ou communes Bien'ici `bienici_places`).
  Ajouter un profil = ajouter une entrée. `min_rent_eur`, `max_rent_eur` et `rooms` sont
  optionnels (`None` = pas de filtre). Deux façons de décrire une recherche :
  - **URL construite** : `lbc_location` / `seloger_locations` (+ budget), comme `enac` ;
  - **URL copiée du site** : `lbc_search_url` / `seloger_search_url`, utilisée telle quelle et
    paginée par `&page=2…` jusqu'à `MAX_PAGES_PER_SITE`, avec en option des recherches de
    **warm-up** (`lbc_warmup_urls` / `seloger_warmup_urls`) visitées avant, comme `blagnac`.
  - **Bien'ici** : `bienici_search_url` = URL de recherche copiée de bienici.com (ex. `blagnac` :
    `/recherche/location/toulouse-31000,blagnac-31700?chambres-min=1&chambres-max=2&balcon-ou-terrasse=oui&tri=publication-desc`).
    Pas de navigateur : communes, chambres, prix, surface, types, options (`balcon-ou-terrasse`,
    `meuble`, `jardin`…) et tri sont traduits en filtres de l'API JSON du site, paginée par 24
    comme la liste du site jusqu'à `bienici_max_pages` (défaut `MAX_PAGES_PER_SITE`). Les
    paramètres `page`/`mode` de l'URL sont ignorés. Sans URL : communes `bienici_places`
    (50 annonces × `BIENICI_MAX_PAGES`), comme `enac`.
- `MAX_RENT_EUR` / `MAX_DISTANCE_KM` : budget et rayon du profil historique `enac`
- `CHROME_BINARY` / `CHROME_DEBUG_PORT` : Chrome utilisé et port CDP (`0` = port libre)
- `MAX_PAGES_PER_SITE` : Nombre de pages à scraper (défaut : 10)
- `PROFILE_SWITCH_MIN_DELAY` / `MAX_DELAY` : pause entre deux recherches d'un même run
- `WARMUP_STEP_MIN/MAX_DELAY` (15–30 s) et `WARMUP_PAGE_MIN/MAX_DELAY` (10–20 s) : cooldowns
  entre étapes de navigation et entre pages, pour les recherches qui ont des warm-ups

### Navigation avec warm-up

Pour une recherche avec warm-up, le scraper suit un parcours « humain » au lieu d'aller
directement sur l'URL de résultats :

```
accueil → warm-up 1 → warm-up 2 … → recherche scannée → page 2 → … → page 10
        (15–30 s entre chaque étape)                  (10–20 s entre chaque page)
```

Chaque étape inclut mouvements de souris, scroll et détection de challenge. La pagination
s'arrête dès qu'une page ne contient plus d'annonces. Un run Blagnac complet (2 sites × 10
pages) prend environ 25 minutes.
- `UI_SECRET_KEY` (variable d'environnement, optionnelle) : clé de session fixe de l'interface

---

## Automatisation

### Avec systemd (recommandé) — 8h, 13h et 19h, ± 20 min

Les unités sont dans `deploy/` (chemins prévus pour `~/Documents/Perso/Scrapper_Annonces`, à adapter sinon).
Le service lance `main.py scrape --enrich --limit 20 --unattended` :

- un captcha est **notifié** et attendu 10 min, puis le site est abandonné sans réessayer ;
- un site bloqué dans les 6 dernières heures est sauté (anti-ban) ;
- un verrou empêche deux runs simultanés (timer + bouton de l'UI).

```bash
systemctl --user link "$PWD/deploy/scraper.service" "$PWD/deploy/scraper.timer"
systemctl --user enable --now scraper.timer
systemctl --user list-timers scraper.timer      # prochain déclenchement
journalctl --user -u scraper.service -f         # suivre un run
```

Chrome n'étant pas headless (DataDome), le service a besoin de la session graphique. Vérifier que
`systemctl --user show-environment | grep DISPLAY` renvoie une valeur ; sinon, une fois par session :
`systemctl --user import-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY`.

Lancer un run tout de suite : `systemctl --user start scraper.service`.

---

## Dépannage

### Problème : Playwright timeout

Augmenter `PAGE_LOAD_TIMEOUT` dans `config.py`.

### Problème : Challenge anti-bot DataDome (LeBonCoin)

LeBonCoin utilise DataDome. En cas de challenge détecté, le script attend 3 min (10 min en mode planifié, avec notification) pour une résolution manuelle. Si l'IP est bloquée :

- Attendre plusieurs heures avant de relancer
- Vérifier que le profil Chrome persistant (`data/browser_profile/`) est bien utilisé
- Ne pas lancer trop de scrapes en succession rapide

Le challenge DataDome s'affiche parfois dans une iframe (`geo.captcha-delivery.com`) avec le
titre « leboncoin.fr » : il est détecté via les frames de la page. La page « Accès temporairement
restreint » (`t:'bv'` dans le HTML) est un ban d'IP, sans captcha à résoudre : il faut attendre.

### Problème : Chrome s'arrête au démarrage (code -5)

Typiquement en lançant depuis le terminal de VS Code installé en **snap** : le snap injecte
`GSETTINGS_SCHEMA_DIR`, `GTK_PATH`, etc., et Chrome plante sur une erreur GLib. Le scraper
retire ces variables avant de lancer Chrome (`scrapers/browser.py::chrome_env`). La sortie de
Chrome est enregistrée dans `logs/chrome_stderr.log`, et ses dernières lignes sont reprises dans
l'erreur affichée.

### Problème : « Profil Chrome déjà utilisé »

Un autre Chrome (scraping ou enrichissement) utilise `data/browser_profile/`. Un verrou
`SingletonLock` laissé par un Chrome mort (crash, kill) est détecté et supprimé automatiquement.
Si le message persiste, c'est qu'un Chrome tourne vraiment : le fermer.

### Problème : peu de cartes par page LeBonCoin (5 au lieu de ~35)

LeBonCoin mélange parfois les attributs des cartes (`data-qa-id="aditem_container"` /
`data-test-id="ad"`). Le scraper garde, page par page, le sélecteur qui trouve le plus de cartes.
Si le log affiche encore « 5 cartes trouvées », capturer la page avec
`scripts/debug/capture_cards_leboncoin.py` et vérifier les sélecteurs de `scrapers/leboncoin.py`.

### Problème : `purge` ne fonctionne pas pour SeLoger/LeBonCoin

Ces sites sont des SPAs — les requêtes HEAD ne permettent pas de détecter les annonces expirées. Utiliser `python main.py check-links` à la place (vérification via Playwright).

### Problème : des annonces en ligne sont marquées « retirées »

`enrich` et `check-links` décident qu'une annonce est retirée via `storage/cleaner.py::page_shows_expired` :
une page dont le JSON embarqué contient l'annonce est en ligne ; sinon, seul le **texte visible** est
comparé aux motifs (« cette annonce n'est plus en ligne »…). Ne jamais chercher ces motifs dans le HTML
complet : les pages LBC embarquent tous leurs messages d'erreur dans leurs scripts (bug corrigé le
2026-11-13). Pour remettre des annonces marquées à tort :
`UPDATE annonces SET status = 'active', enrichment_status = 'pending', enrichment_attempts = 0 WHERE id IN (…);`

### Alerte « Extraction dégradée » après un scrape

Le contrôle de santé compare le taux de remplissage des champs clés aux seuils de
`QUALITY_MIN_FILL_RATES` (`config.py`). Après un scrape, il juge les fiches lues depuis le JSON de la
page de recherche, **sans** les champs que cette page ne fournit pas (`QUALITY_SEARCH_SKIP_FIELDS` :
la recherche LBC n'a pas de description, contrôlée après `enrich`). Détail : `python main.py quality`.

### Problème : Aucune coordonnée trouvée pour une adresse

Le géocodeur Nominatim est parfois limité en débit ou ne reconnaît pas certains formats d'adresses. Vérifiez les logs dans `logs/geo.log`.

### Problème : Import errors

Assurez-vous d'être dans le bon répertoire et d'avoir activé l'environnement virtuel :

```bash
cd toulouse_rent_scraper
source ../venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python main.py
```

---

## Logs

Les logs sont créés dans `logs/` :

- `main.log` : Pipeline principal
- `seloger.log` : Scraper SeLoger
- `bienici.log` : Source Bien'ici (API)
- `geo.log` : Géolocalisation

---

## Contribuer (ajouter un nouveau scraper)

1. Créer `scrapers/nom_du_site.py` héritant de `BaseScraper`
2. Implémenter les méthodes abstraites (`card_selector`, `extract_annonce`, etc.)
3. Ajouter l'option CLI dans `main.py`

---

## Améliorations

- [x] Scraper multi-sites (SeLoger, LeBonCoin, Bien'ici)
- [x] Rapports Markdown automatiques
- [x] Export CSV/JSON (`--export`)
- [x] Interface Web Flask (`--ui`)
- [x] Vérification liens Playwright (`--check-links`)
- [ ] Enrichissement des données (surface, DPE, description) — Sprint 3
- [ ] Scraper PAP.fr — Sprint 4
- [ ] Système de scoring 0-100 — Sprint 5
- [ ] Notifications email/Telegram
- [ ] Dashboard Streamlit / API REST

---

## Licence

Usage personnel — ENAC Toulouse

---

**Dernière mise à jour :** 2026-03-03
