# Sprint 4 — Nouveau scraper : PAP.fr (Particulier à Particulier)

**Objectif** : Ajouter PAP.fr comme troisième source d'annonces. PAP est idéal car les annonces sont postées directement par les propriétaires (pas de frais d'agence), ce qui est particulièrement intéressant pour un budget étudiant ENAC.

**Durée estimée** : 1 semaine

---

## Pourquoi PAP.fr ?

| Critère | PAP.fr | Autres options écartées |
|---------|--------|----------------------|
| **Sans frais d'agence** | Oui (100% particuliers) | Bien'ici = agrégateur, Logic-Immo = agences |
| **Volume Toulouse** | Bon volume | LocService = faible volume |
| **Anti-bot** | Modéré (pas de DataDome) | — |
| **Pertinence étudiant** | Forte (petits budgets) | Studapart = résidences étudiantes uniquement |
| **Données riches** | Surface, DPE, photos, charges | — |

---

## Tâches

### 4.1 Analyse et reconnaissance PAP.fr (Priorité: Haute | Effort: S)

**Actions** :
- Naviguer manuellement sur PAP.fr, identifier :
  - URL de recherche avec filtres (Toulouse, location, budget max 500€)
  - Structure HTML des cartes de résultats (classes CSS, attributs data-*)
  - Structure HTML des pages de détail
  - Mécanismes anti-bot (Captcha, rate limiting, User-Agent check)
  - Pagination (URL params ou bouton "Page suivante")
- Capturer le HTML brut avec un script de debug (`debug_card_html_pap.py`)
- Documenter les sélecteurs identifiés

**Livrable** : Document `docs/pap_selectors.md` avec les sélecteurs validés.

---

### 4.2 Configuration PAP (Priorité: Haute | Effort: S)

**Actions** :
- Ajouter dans `config.py` :
  ```python
  # PAP.fr
  PAP_BASE_URL = "https://www.pap.fr"
  PAP_SEARCH_URL = (
      "https://www.pap.fr/annonce/location-appartement-toulouse-31-"
      "?prix-max=500&surface-min=10"
  )
  ```
- URL de navigation progressive (si nécessaire pour anti-bot)
- Ajouter les étapes intermédiaires si PAP détecte les accès directs

**Critère de validation** : Les URLs de recherche retournent des résultats valides dans le navigateur.

---

### 4.3 Scraper PAP (Priorité: Haute | Effort: L)

**Actions** :
- Créer `scrapers/pap.py` héritant de `BaseScraper` :
  - `site_name()` → `"PAP"`
  - `base_url()` → `PAP_BASE_URL`
  - `search_url()` → `PAP_SEARCH_URL`
  - `card_selector()` → sélecteur identifié en 4.1
  - `extract_annonce(card)` :
    - Titre : texte du lien principal
    - Prix : extraction depuis le bloc prix (format "XXX €/mois")
    - Localisation : quartier / code postal
    - URL : lien vers la page de détail
    - Surface : souvent visible sur la carte (PAP affiche plus d'infos que LBC)
  - `navigation_steps()` : étapes pour simuler un utilisateur réel
  - Gestion de la pagination PAP
- Ajouter `PAPScraper` dans `scrapers/__init__.py` :
  ```python
  SCRAPERS = [SeLogerScraper, LeBonCoinScraper, PAPScraper]
  ```
- Ajouter l'option CLI `--pap` dans `main.py`

**Critère de validation** : `python main.py --pap` récupère et stocke des annonces PAP valides.

---

### 4.4 Extracteur détaillé PAP (Priorité: Moyenne | Effort: M)

**Actions** :
- Créer `scrapers/detail_extractors/pap_detail.py` :
  - Extraire les données enrichies depuis la page de détail PAP :
    - Description complète
    - Surface, pièces, étage, meublé/non
    - Charges, dépôt de garantie
    - DPE / GES
    - Photos
    - Date de mise en ligne
    - Contact (nom du particulier)
  - PAP a généralement moins de protection anti-bot que LBC, donc l'enrichissement est plus facile
- Intégrer dans le pipeline d'enrichissement (`enricher.py` du Sprint 3)

**Critère de validation** : `python main.py --enrich` enrichit aussi les annonces PAP.

---

### 4.5 Tests PAP (Priorité: Moyenne | Effort: S)

**Actions** :
- `tests/test_pap.py` :
  - Tests de configuration (site_name, base_url, search_url)
  - Tests d'extraction avec mock de carte HTML
  - Tests de construction d'URL
  - Tests de l'extracteur détaillé avec mock HTML
- Ajout d'un `sample_annonce_pap` dans `conftest.py`

**Critère de validation** : `pytest tests/test_pap.py -v` tout vert.

---

### 4.6 Gestion multi-sites améliorée (Priorité: Moyenne | Effort: S)

**Actions** :
- Mettre à jour le CLI pour supporter les combinaisons :
  ```bash
  python main.py --pap                    # PAP seul
  python main.py --seloger --pap          # SeLoger + PAP
  python main.py --all                    # Tous (SeLoger + LBC + PAP)
  ```
- Remplacer `mutually_exclusive_group` par des flags indépendants
- Mettre à jour les rapports pour afficher la source (déjà le champ `site`)
- Stats par site dans le résumé global

**Critère de validation** : `python main.py --seloger --pap` ne lance que ces deux scrapers.

---

## Résumé

| # | Tâche | Priorité | Effort | Dépendance |
|---|-------|----------|--------|------------|
| 4.1 | Analyse et reconnaissance PAP | Haute | S | — |
| 4.2 | Configuration PAP | Haute | S | 4.1 |
| 4.3 | Scraper PAP | Haute | L | 4.1, 4.2 |
| 4.4 | Extracteur détaillé PAP | Moyenne | M | 4.3, Sprint 3 |
| 4.5 | Tests PAP | Moyenne | S | 4.3 |
| 4.6 | Gestion multi-sites améliorée | Moyenne | S | 4.3 |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure cible après Sprint 4

```
toulouse_rent_scraper/
├── scrapers/
│   ├── base.py
│   ├── seloger.py
│   ├── leboncoin.py
│   ├── pap.py                         # NOUVEAU
│   ├── enricher.py
│   └── detail_extractors/
│       ├── seloger_detail.py
│       ├── leboncoin_detail.py
│       └── pap_detail.py              # NOUVEAU
├── tests/
│   ├── test_pap.py                    # NOUVEAU
│   └── ...
└── docs/
    └── pap_selectors.md               # NOUVEAU
```

---

## Notes anti-bot PAP

PAP.fr est généralement moins agressif que LeBonCoin (pas de DataDome) mais applique :
- Rate limiting classique (429 Too Many Requests)
- Vérification User-Agent basique
- Parfois un Captcha simple (hCaptcha) sur les accès répétés

**Stratégie recommandée** :
- Réutiliser le profil Chrome persistant
- Délais standards (3-7s entre pages)
- Navigation progressive : accueil → recherche → résultats
- Si hCaptcha : même mécanisme de pause + résolution manuelle que pour LBC
