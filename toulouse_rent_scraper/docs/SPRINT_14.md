# Sprint 14 — Profils de recherche multiples (cas d'usage Blagnac)

> **Date** : —
> **Statut** : 🔲 À faire
> **Prérequis** : [Sprint 11](SPRINT_11.md) (parse_price ≥ 1000 €, URLs dérivées de la config, géocodage hors Toulouse)
> **Recommandé avant** : [Sprint 12](SPRINT_12.md) / [Sprint 13](SPRINT_13.md) — les notifications et le score deviennent « par profil »

## Objectif

Le système est aujourd'hui câblé sur **un seul cas d'usage** : studio ≤ 500 € à ≤ 10 km de l'ENAC
(`ENAC_LATITUDE`, `MAX_RENT_EUR`, colonne `distance_enac_km`, libellés « ENAC » dans l'UI et les rapports).

Ajouter un **second cas d'usage** et rendre le pipeline générique :

| Profil | Cible | Budget | Rayon | Types |
|--------|-------|--------|-------|-------|
| `enac` (existant) | ENAC — 7 av. Édouard Belin, 31400 Toulouse (43.5643, 1.4800) | 50 → 500 € | 10 km | studio, T1 |
| **`blagnac`** (nouveau) | **14 Pl. Marcel Dassault, 31700 Blagnac** — quartier Font-Grasse (**43.6417, 1.3693**, géocodé Nominatim le 2026-11-03) | **≈ 700 €** → plage 550 → 750 € | 8 km | appartement T1 → T3 |

> Le rayon de 8 km couvre Blagnac, Beauzelle, Cornebarrieu, Colomiers-est, Aussonne, Purpan, Saint-Cyprien, Les Sept Deniers, Ancely, Lardenne et le centre de Toulouse ouest (Compans-Caffarelli ≈ 6 km). Le tram **T1** (Aéroconstellation ↔ Palais de Justice) dessert la zone : à exploiter si 13.5 (temps de trajet) est fait.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 14.1 | `SEARCH_PROFILES` dans la config | 🔲 | Remplace les constantes ENAC/MAX_RENT globales |
| 14.2 | URLs de recherche par profil | 🔲 | LBC + SeLoger pour Blagnac |
| 14.3 | Modèle de données multi-profils | 🔲 | Table `annonce_profiles` |
| 14.4 | Filtre et pipeline par profil | 🔲 | Une annonce peut matcher plusieurs profils |
| 14.5 | CLI `--profile` | 🔲 | Défaut : tous les profils actifs |
| 14.6 | UI : sélecteur de profil | 🔲 | Liste, carte, export Markdown |
| 14.7 | Rapports & exports par profil | 🔲 | `reporting/` |
| 14.8 | Tests | 🔲 | Profils, migration, filtre |

---

## 14.1 — `SEARCH_PROFILES` dans la config

**Fichier** : `config.py`

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SearchProfile:
    key: str
    label: str                 # affiché dans l'UI / notifications
    target_address: str
    target_lat: float
    target_lon: float
    max_distance_km: float
    min_rent_eur: int
    max_rent_eur: int
    estate_types: tuple        # ("studio", "T1", "T2", "T3")
    enabled: bool = True

SEARCH_PROFILES = {
    "enac": SearchProfile(
        key="enac", label="ENAC",
        target_address="7 Avenue Édouard Belin, 31400 Toulouse",
        target_lat=43.5643, target_lon=1.4800,
        max_distance_km=10, min_rent_eur=50, max_rent_eur=500,
        estate_types=("studio", "T1"),
    ),
    "blagnac": SearchProfile(
        key="blagnac", label="Blagnac — Pl. Marcel Dassault",
        target_address="14 Place Marcel Dassault, 31700 Blagnac",
        target_lat=43.6417, target_lon=1.3693,
        max_distance_km=8, min_rent_eur=550, max_rent_eur=750,
        estate_types=("T1", "T2", "T3"),
    ),
}
```

- Garder temporairement `ENAC_LATITUDE`, `MAX_RENT_EUR`, etc. comme **alias** vers `SEARCH_PROFILES["enac"]` pour ne pas casser le code existant pendant la migration ; les supprimer en fin de sprint.
- `MIN_RENT_EUR` reste le garde-fou contre les prix aberrants → devient `min_rent_eur` par profil.
- Ajouter à `KNOWN_COMMUNES` (11.4) : Blagnac, Beauzelle, Cornebarrieu, Aussonne, Colomiers, Mondonville, Seilh.

## 14.2 — URLs de recherche par profil

**Fichiers** : `config.py`, `scrapers/seloger.py`, `scrapers/leboncoin.py`

Chaque scraper reçoit le profil : `SeLogerScraper(profile)`, `LeBonCoinScraper(profile)` ; `search_urls()` construit l'URL depuis le profil (suite logique de 11.5).

- **LeBonCoin** — format `locations=<Ville>__<lat>_<lon>_<?>_<rayon_m>` (cf. URL Toulouse actuelle). Pour Blagnac :
  ```
  https://www.leboncoin.fr/recherche?category=10
    &locations=Blagnac__43.6417_1.3693_5000_8000
    &price=550-750
    &real_estate_type=2
    &rooms=1-3
    &sort=time&order=desc
  ```
  ⚠️ Le 3ᵉ nombre du paramètre `locations` n'est pas documenté : **capturer l'URL réelle** en faisant la recherche à la main dans Chrome (profil persistant) puis la reporter dans le profil.
- **SeLoger** — `locations` est un JSON base64 (`placeId`, `radius`, `polyline`) : impossible à générer de façon fiable. **Capturer l'URL** depuis le site (Blagnac, rayon 8 km, T1–T3, loyer max 750 €) et la stocker par profil :
  ```python
  SELOGER_LOCATIONS = {"enac": _SELOGER_LOCATIONS_ENAC, "blagnac": "<base64 capturé>"}
  ```
  Les autres paramètres (`maxPrice`, `estateSubTypes`, `page`) sont générés depuis le profil.
- `navigation_steps()` de LBC : l'étape « Toulouse » devient l'étape « ville du profil ».
- Anti-bot : enchaîner les profils **dans la même session Chrome** avec un délai long (60–120 s) entre deux recherches, et ne pas lancer plus de 2 profils × 2 sites par run.

## 14.3 — Modèle de données multi-profils

**Fichier** : `storage/sqlite.py` (ou `storage/db.py` si Sprint 12 fait)

Une même annonce peut intéresser plusieurs profils (ex. T1 à 600 € à Saint-Cyprien : < 8 km de Blagnac, mais > 500 € pour l'ENAC — ou l'inverse pour un studio à Purpan). On sépare donc l'annonce de sa pertinence :

```sql
CREATE TABLE IF NOT EXISTS annonce_profiles (
    annonce_id  INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,
    profile     TEXT    NOT NULL,
    distance_km REAL,
    score       REAL,                 -- Sprint 13.3
    status      TEXT DEFAULT 'active',-- 'hidden' par profil (11.3)
    matched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (annonce_id, profile)
);
CREATE INDEX IF NOT EXISTS idx_ap_profile ON annonce_profiles(profile);
```

- **Migration** : pour chaque annonce existante, `INSERT INTO annonce_profiles (annonce_id, profile, distance_km) SELECT id, 'enac', distance_enac_km FROM annonces`.
- `distance_enac_km` est conservée (lecture seule, compat) puis supprimée au Sprint 12.4.
- Ajouter `lat` / `lon` sur `annonces` (copiés depuis `geocoding_cache`) : la distance à n'importe quel profil se recalcule sans re-géocoder, et la carte n'a plus besoin du `LEFT JOIN`.
- Masquer une annonce (11.3) se fait **par profil** : un T2 masqué pour Blagnac reste visible pour un autre profil.

## 14.4 — Filtre et pipeline par profil

**Fichiers** : `filters/price_and_distance.py`, `geo/distance.py`, `main.py` (ou `pipeline.py`)

- `distance_from_enac_km(addr)` → `distance_km(addr, target: tuple[float, float])` ; garder un wrapper pour l'ENAC le temps de la migration.
- `apply_price_and_distance_filter(annonce)` → `match_profiles(annonce, profiles) -> list[(profile, distance_km)]` :
  - géocode **une seule fois** (cache) ;
  - teste chaque profil actif (budget + rayon + type si connu) ;
  - renvoie la liste des profils qui matchent (vide ⇒ rejet).
- Pipeline : `insert_annonce` puis `upsert_annonce_profile(annonce_id, profile, distance)` pour chaque match. Le statut `new` est calculé **par profil** (une annonce déjà connue pour l'ENAC peut être « nouvelle » pour Blagnac → notification Blagnac).
- Un scraping lancé pour le profil Blagnac teste quand même les annonces contre tous les profils (gratuit, et ça évite de rater des recoupements).
- Résumé de fin de run : compteurs par site **et** par profil.

## 14.5 — CLI `--profile`

```
python main.py --all                       # tous les profils actifs
python main.py --leboncoin --profile blagnac
python main.py --enrich --profile blagnac --limit 20
```

- `--profile` accepte une clé de `SEARCH_PROFILES` (choices générés depuis la config), répétable.
- `/start-scraping` (UI) passe le profil sélectionné.

## 14.6 — UI : sélecteur de profil

**Fichier** : `ui.py` (ou `ui/` après 12.5)

- Sélecteur de profil en tête (onglets « ENAC » / « Blagnac »), mémorisé en `localStorage` et passé en `?profile=` ; défaut = premier profil actif.
- Requêtes : `JOIN annonce_profiles ap ON ap.annonce_id = a.id AND ap.profile = ?` ; tri « distance » sur `ap.distance_km`.
- Filtres prix pré-remplis avec `min_rent_eur` / `max_rent_eur` du profil.
- Libellés : « Distance ENAC » → « Distance {profile.label} ».
- Carte : centrée sur la cible du profil, marqueur cible avec `target_address`, cercle du rayon `max_distance_km`.
- Badge « Aussi pour ENAC » quand une annonce matche plusieurs profils.
- Export Markdown (`/export-document`) : titre « Dossier de candidature — Blagnac », critère « Distance cible acceptable ».

## 14.7 — Rapports & exports par profil

**Fichiers** : `reporting/generator.py`, `reporting/exporter.py`

- Rapports générés par profil : `reports/<profile>/nouvelles_annonces.md`, etc.
- Export CSV/JSON : colonnes `profile`, `distance_km` (une ligne par couple annonce × profil) ; option `--profile`.

## 14.8 — Tests

- `tests/test_profiles.py` : un studio 480 € à Rangueil matche `enac` seulement ; un T2 700 € à Blagnac matche `blagnac` seulement ; un T1 520 € à Purpan → aucun (hors budget ENAC, sous le min Blagnac) ; un T1 600 € à Saint-Cyprien → `blagnac`.
- Migration : base existante → toutes les annonces rattachées à `enac` avec la même distance.
- Statut `new` par profil ; masquage par profil.
- Mise à jour des fixtures qui utilisent `distance_enac_km` (`tests/conftest.py`, `test_enricher.py`, `test_exporter.py`, `test_cleaner.py`).

---

## Fichiers impactés (référence `distance_enac_km` / constantes ENAC)

`config.py`, `main.py`, `filters/price_and_distance.py`, `geo/distance.py`, `storage/sqlite.py`, `ui.py` (7 occurrences), `reporting/generator.py` (5), `reporting/exporter.py`, `scrapers/seloger.py`, `scrapers/leboncoin.py`, tests listés en 14.8.

## Critères d'acceptation

- [ ] `python main.py --leboncoin --profile blagnac` ramène des annonces 550–750 € autour de Blagnac, stockées avec leur distance à la Pl. Marcel Dassault.
- [ ] Les données ENAC existantes sont intactes après migration (même nombre d'annonces et mêmes distances dans le profil `enac`).
- [ ] L'UI bascule ENAC ↔ Blagnac : liste, filtres, carte (centre + rayon) et export suivent le profil.
- [ ] Ajouter un 3ᵉ profil = ajouter une entrée dans `SEARCH_PROFILES` (+ URL SeLoger capturée), sans autre changement de code.
- [ ] `pytest` vert.
