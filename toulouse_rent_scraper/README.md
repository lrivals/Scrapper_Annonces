# Toulouse Rent Scraper - ENAC

🏠 **Scraper d'annonces de location à Toulouse**, avec filtrage automatique par distance de l'ENAC et par prix.

---

## 🎯 Objectif

Rechercher automatiquement des annonces de location :
- 📍 **Proches de l'ENAC** (Rangueil/Ramonville)
- 💰 **Loyer ≤ 450€**
- 🔗 **Avec lien direct vers l'annonce**

---

## ⚙️ Installation

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

## 🚀 Utilisation

### Lancer le scraper

```bash
python main.py
```

Le script va :
1. **Scraper** SeLoger avec les critères définis
2. **Filtrer** les annonces par prix et distance ENAC
3. **Stocker** les nouvelles annonces dans `data/annonces.sqlite`
4. **Générer** des logs dans `logs/`

### Consulter les résultats

Les annonces sont stockées dans `data/annonces.sqlite`. Vous pouvez les consulter avec :

```bash
sqlite3 data/annonces.sqlite "SELECT title, price, distance_enac_km, url FROM annonces ORDER BY distance_enac_km;"
```

---

## 🧪 Tests

Lancer les tests unitaires :

```bash
pytest tests/ -v
```

Avec couverture :

```bash
pytest tests/ --cov=. --cov-report=html
```

---

## 📁 Structure du projet

```
toulouse_rent_scraper/
├── config.py              # Configuration globale
├── main.py                # Point d'entrée du pipeline
├── requirements.txt       # Dépendances Python
│
├── scrapers/              # Scrapers par site
│   └── seloger.py
│
├── filters/               # Filtres métier
│   └── price_and_distance.py
│
├── storage/               # Stockage SQLite
│   └── sqlite.py
│
├── geo/                   # Géolocalisation
│   └── distance.py
│
├── utils/                 # Utilitaires
│   ├── logger.py          # Système de logging
│   ├── validation.py      # Validation des données
│   └── retry.py           # Retry avec backoff
│
├── tests/                 # Tests unitaires
│   ├── conftest.py
│   ├── test_filters.py
│   ├── test_storage.py
│   └── test_validation.py
│
├── data/                  # Données générées
│   └── annonces.sqlite
│
└── logs/                  # Logs d'exécution
    └── main.log
```

---

## ⚙️ Configuration

Modifiez `config.py` pour ajuster :
- **MAX_RENT_EUR** : Prix maximum (défaut : 450€)
- **MAX_DISTANCE_KM** : Distance maximale de l'ENAC (défaut : 5km)
- **HEADLESS_BROWSER** : Navigateur en mode headless (défaut : True)
- **MAX_PAGES_PER_SITE** : Nombre de pages à scraper (défaut : 10)

---

## 🔄 Automatisation

### Avec cron (toutes les 8 heures)

```bash
crontab -e
```

Ajouter :

```cron
0 */8 * * * /home/user/Scrapper_Annonces/venv/bin/python /home/user/Scrapper_Annonces/toulouse_rent_scraper/main.py
```

---

## 🐛 Dépannage

### Problème : Playwright timeout

**Solution** : Augmenter `PAGE_LOAD_TIMEOUT` dans `config.py` ou désactiver le mode headless :

```python
HEADLESS_BROWSER = False
```

### Problème : Aucune coordonnée trouvée pour une adresse

**Solution** : Le géocodeur Nominatim a parfois du mal avec certaines adresses. Vérifiez les logs dans `logs/geo.log` pour plus de détails.

### Problème : Import errors

**Solution** : Assurez-vous d'être dans le bon répertoire et d'avoir activé l'environnement virtuel :

```bash
cd toulouse_rent_scraper
source ../venv/bin/activate
export PYTHONPATH=$(pwd):$PYTHONPATH
python main.py
```

---

## 📝 Logs

Les logs sont créés dans le répertoire `logs/` :
- `main.log` : Pipeline principal
- `seloger.log` : Scraper SeLoger
- `geo.log` : Géolocalisation

---

## 🤝 Contribution

Pour ajouter un nouveau scraper (LeBonCoin, PAP, etc.) :

1. Créer `scrapers/nom_du_site.py`
2. Implémenter `scrape_nom_du_site()` qui retourne `List[Dict]`
3. Ajouter l'appel dans `main.py`

---

## 📜 Licence

Usage personnel - ENAC Toulouse

---

## 🔧 Améliorations futures

- [ ] Scraper multi-sites (LeBonCoin, PAP)
- [ ] Notifications par email/Telegram
- [ ] Dashboard de visualisation (Streamlit)
- [ ] API REST
- [ ] Export CSV/JSON

---

**Dernière mise à jour :** 2026-02-06
