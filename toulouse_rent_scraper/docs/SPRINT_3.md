# Sprint 3 — Enrichissement des annonces (scraping approfondi)

**Objectif** : Ouvrir individuellement chaque annonce en base pour récupérer les informations détaillées absentes des cartes de résultats (surface, nombre de pièces, description, photos, etc.).

**Durée estimée** : 1 semaine

---

## Contexte

Actuellement, le scraper ne récupère que les données visibles sur les **cartes de résultats** :
- Titre, prix, localisation, lien

En ouvrant chaque lien individuellement, on peut extraire beaucoup plus :
- Surface (m²), nombre de pièces, étage
- Description complète du propriétaire/agence
- Charges (incluses ou non), dépôt de garantie
- Photos (URLs)
- Date de publication, disponibilité
- Contact (agence ou particulier)
- DPE (diagnostic énergétique)

---

## Tâches

### 3.1 Nouveau schéma DB enrichi (Priorité: Haute | Effort: S)

**Actions** :
- Ajouter les colonnes à la table `annonces` via migration automatique :
  ```sql
  surface_m2 REAL,
  nb_rooms INTEGER,
  nb_bedrooms INTEGER,
  floor INTEGER,
  description TEXT,
  charges INTEGER,
  deposit INTEGER,
  furnished BOOLEAN,
  dpe_rating TEXT,
  photos TEXT,          -- JSON array d'URLs
  publisher_type TEXT,  -- "particulier" ou "agence"
  published_at TEXT,
  enriched_at TIMESTAMP,
  enrichment_status TEXT DEFAULT 'pending'  -- pending/done/error
  ```
- Migration automatique dans `init_db()` (même pattern que `created_at`)
- `enrichment_status` permet de savoir quelles annonces ont déjà été enrichies

**Critère de validation** : `init_db()` ajoute les nouvelles colonnes sans perdre les données existantes.

---

### 3.2 Extracteur détaillé SeLoger (Priorité: Haute | Effort: M)

**Actions** :
- Créer `scrapers/detail_extractors/seloger_detail.py` :
  - Fonction `extract_detail(page, url) -> dict`
  - Ouvrir la page de l'annonce
  - Extraire via sélecteurs `data-testid` :
    - Surface : `[data-testid="annotatedDescription-surface"]` ou similaire
    - Pièces : nombre dans le bloc caractéristiques
    - Description : bloc texte principal
    - Prix charges : mention "CC" ou "HC"
    - Photos : URLs des images dans le carrousel
    - DPE : classe énergétique (A-G)
    - Type de contact : agence vs particulier
  - Gestion des erreurs (page 404, timeout, anti-bot)

**Critère de validation** : Pour une annonce SeLoger, on récupère au minimum surface + nb_rooms + description.

---

### 3.3 Extracteur détaillé LeBonCoin (Priorité: Haute | Effort: M)

**Actions** :
- Créer `scrapers/detail_extractors/leboncoin_detail.py` :
  - Fonction `extract_detail(page, url) -> dict`
  - Extraire via sélecteurs `data-test-id` :
    - Surface : critère "Surface" dans la liste des caractéristiques
    - Pièces : critère "Pièces"
    - Meublé : critère "Meublé"
    - Description : `[data-test-id="ad_description"]`
    - Photos : URLs du carrousel d'images
    - DPE : `[data-test-id="energy"]`
    - Type : "Professionnel" ou "Particulier"
  - Scroll into view pour déclencher le lazy-loading des images
  - Délais anti-détection entre chaque page détail

**Critère de validation** : Pour une annonce LBC, on récupère surface + description + photos.

---

### 3.4 Pipeline d'enrichissement (Priorité: Haute | Effort: M)

**Actions** :
- Créer `scrapers/enricher.py` :
  - Fonction `enrich_annonces(site_filter=None, limit=50)` :
    1. Récupère les annonces avec `enrichment_status = 'pending'`
    2. Pour chaque annonce, ouvre le lien dans le navigateur
    3. Appelle l'extracteur détaillé correspondant au site
    4. Met à jour la ligne en base avec les nouvelles données
    5. Marque `enrichment_status = 'done'` et `enriched_at = now()`
    6. En cas d'erreur → `enrichment_status = 'error'`
  - Rate limiting : délai aléatoire 5-10s entre chaque page détail
  - Limite configurable (éviter de tout faire d'un coup)
  - Réutilise la session Playwright existante (même profil Chrome)
- Ajouter option CLI `--enrich` dans `main.py` :
  - `python main.py --enrich` — enrichit les annonces pending
  - `python main.py --enrich --limit 10` — enrichit max 10 annonces
  - `python main.py --all --enrich` — scrape puis enrichit

**Critère de validation** : `python main.py --enrich --limit 5` ouvre 5 annonces, récupère les détails, et met à jour la DB.

---

### 3.5 Mise à jour des rapports enrichis (Priorité: Moyenne | Effort: S)

**Actions** :
- Mettre à jour `reporting/generator.py` pour inclure les nouvelles données :
  - `nouvelles_annonces.md` : ajouter surface, pièces, meublé/non, DPE
  - `toutes_les_annonces.md` : colonnes supplémentaires (surface, pièces)
  - Nouveau rapport `annonces_detaillees.md` : format long avec description complète et liens photos
- Indicateur d'enrichissement : marquer les annonces non encore enrichies

**Critère de validation** : Les rapports affichent les infos enrichies quand disponibles.

---

### 3.6 Tests enrichissement (Priorité: Moyenne | Effort: S)

**Actions** :
- Tests unitaires pour les extracteurs détaillés (mock HTML)
- Tests pour le pipeline d'enrichissement (mock DB + pages)
- Tests de migration DB (nouvelles colonnes)
- Test d'intégration : insertion → enrichissement → vérification DB

**Critère de validation** : `pytest tests/ -v` tout vert, couverture des nouveaux modules.

---

## Résumé

| # | Tâche | Priorité | Effort | Dépendance |
|---|-------|----------|--------|------------|
| 3.1 | Schéma DB enrichi | Haute | S | — |
| 3.2 | Extracteur détaillé SeLoger | Haute | M | 3.1 |
| 3.3 | Extracteur détaillé LeBonCoin | Haute | M | 3.1 |
| 3.4 | Pipeline d'enrichissement | Haute | M | 3.2, 3.3 |
| 3.5 | Rapports enrichis | Moyenne | S | 3.4 |
| 3.6 | Tests enrichissement | Moyenne | S | 3.2, 3.3, 3.4 |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure cible après Sprint 3

```
toulouse_rent_scraper/
├── scrapers/
│   ├── base.py
│   ├── seloger.py
│   ├── leboncoin.py
│   ├── enricher.py                   # NOUVEAU — pipeline d'enrichissement
│   └── detail_extractors/            # NOUVEAU
│       ├── __init__.py
│       ├── seloger_detail.py
│       └── leboncoin_detail.py
└── tests/
    ├── test_enricher.py              # NOUVEAU
    └── test_detail_extractors.py     # NOUVEAU
```

---

## Anti-bot : précautions

L'enrichissement ouvre beaucoup de pages individuelles, ce qui augmente le risque de détection :
- Délai **5-10s** entre chaque page détail (vs 3-7s entre pages de résultats)
- Limiter à **20-30 annonces par session** d'enrichissement
- Répartir sur plusieurs heures si besoin (`--limit`)
- Réutiliser le même profil Chrome avec cookies
- En cas de challenge DataDome → pause + résolution manuelle
