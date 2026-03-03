# Toulouse Rent Scraper - ENAC

Scraper d'annonces de location à Toulouse, avec filtrage automatique par distance de l'ENAC et par prix.

---

## Objectif

Rechercher automatiquement des annonces de location :

- Proches de l'ENAC (Rangueil/Ramonville)
- Loyer ≤ 500€
- Distance ≤ 10 km de l'ENAC
- Avec lien direct vers l'annonce

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
pip install -r requirements.txt
```

### 4. Installer Playwright

```bash
playwright install chromium
```

---

## Utilisation

### Lancer le scraper

```bash
python main.py
```

Le script va :

1. Scraper SeLoger et LeBonCoin avec les critères définis
2. Filtrer les annonces par prix et distance ENAC
3. Stocker les nouvelles annonces dans `data/annonces.sqlite`
4. Générer des rapports Markdown dans `reports/`
5. Générer des logs dans `logs/`

### Options CLI

```bash
python main.py --seloger          # SeLoger uniquement
python main.py --leboncoin        # LeBonCoin uniquement
python main.py --all              # Tous les sites (défaut)
python main.py --export csv       # Exporter en CSV après le scrape
python main.py --export json      # Exporter en JSON après le scrape
python main.py --purge            # Vérifier les annonces expirées (HEAD requests)
python main.py --ui               # Lancer l'interface web Flask (port 5000)
python main.py --port 8080        # Lancer l'interface sur un port personnalisé
python main.py --check-links      # Vérifier les liens via Playwright
python main.py --limit 20         # Limiter le nombre de liens vérifiés
```

### Interface Web

```bash
python main.py --ui
```

Ouvre `http://localhost:5000` — interface responsive pour :

- Consulter toutes les annonces avec filtres (site, statut, prix)
- Trier par prix, distance ou date
- Supprimer les annonces manuellement

### Consulter les résultats

Après chaque exécution, deux rapports sont générés dans `reports/` :

- `nouvelles_annonces.md` — Les annonces ajoutées lors de cette exécution
- `toutes_les_annonces.md` — Tableau complet de toutes les annonces en base

Requête directe sur la base :

```bash
sqlite3 data/annonces.sqlite "SELECT title, price, distance_enac_km, url FROM annonces ORDER BY distance_enac_km;"
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
├── config.py              # Configuration globale
├── main.py                # Point d'entrée du pipeline
├── ui.py                  # Interface web Flask
├── requirements.txt       # Dépendances Python
│
├── scrapers/              # Scrapers par site
│   ├── base.py            # Classe abstraite (Playwright + anti-bot)
│   ├── seloger.py
│   └── leboncoin.py
│
├── filters/               # Filtres métier
│   └── price_and_distance.py
│
├── storage/               # Stockage SQLite
│   ├── sqlite.py
│   └── cleaner.py         # Vérification des liens expirés
│
├── reporting/             # Génération de rapports
│   ├── generator.py       # Rapports Markdown
│   └── exporter.py        # Export CSV/JSON
│
├── geo/                   # Géolocalisation
│   └── distance.py        # Geocoding Nominatim + distance ENAC
│
├── utils/                 # Utilitaires
│   ├── logger.py          # Logging rotatif
│   ├── validation.py      # Validation des données
│   └── retry.py           # Retry avec backoff exponentiel
│
├── tests/                 # Tests unitaires (~85% de couverture)
│   ├── conftest.py
│   ├── test_filters.py
│   ├── test_validation.py
│   ├── test_storage.py
│   ├── test_cleaner.py
│   ├── test_exporter.py
│   └── test_leboncoin.py
│
├── docs/                  # Documentation des sprints
│   ├── ROADMAP.md
│   ├── SPRINT_1.md
│   └── ...
│
├── reports/               # Rapports générés (gitignored)
│   ├── nouvelles_annonces.md
│   └── toutes_les_annonces.md
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

- `MAX_RENT_EUR` : Prix maximum (défaut : 500€)
- `MAX_DISTANCE_KM` : Distance maximale de l'ENAC (défaut : 10 km)
- `HEADLESS_BROWSER` : Navigateur en mode headless (défaut : False)
- `MAX_PAGES_PER_SITE` : Nombre de pages à scraper (défaut : 10)

---

## Automatisation

### Avec cron (toutes les 8 heures)

```bash
crontab -e
```

Ajouter :

```cron
0 */8 * * * /home/user/Scrapper_Annonces/venv/bin/python /home/user/Scrapper_Annonces/toulouse_rent_scraper/main.py
```

---

## Dépannage

### Problème : Playwright timeout

Augmenter `PAGE_LOAD_TIMEOUT` dans `config.py` ou désactiver le mode headless :

```python
HEADLESS_BROWSER = False
```

### Problème : Challenge anti-bot DataDome (LeBonCoin)

LeBonCoin utilise DataDome. En cas de challenge détecté, le script attend 180 secondes pour une résolution manuelle. Si l'IP est bloquée :

- Attendre plusieurs heures avant de relancer
- Vérifier que le profil Chrome persistant (`data/browser_profile/`) est bien utilisé
- Ne pas lancer trop de scrapes en succession rapide

### Problème : `--purge` ne fonctionne pas pour SeLoger/LeBonCoin

Ces sites sont des SPAs — les requêtes HEAD ne permettent pas de détecter les annonces expirées. Utiliser `--check-links` à la place (vérification via Playwright).

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
- `geo.log` : Géolocalisation

---

## Contribuer (ajouter un nouveau scraper)

1. Créer `scrapers/nom_du_site.py` héritant de `BaseScraper`
2. Implémenter les méthodes abstraites (`card_selector`, `extract_annonce`, etc.)
3. Ajouter l'option CLI dans `main.py`

---

## Améliorations

- [x] Scraper multi-sites (SeLoger, LeBonCoin)
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
