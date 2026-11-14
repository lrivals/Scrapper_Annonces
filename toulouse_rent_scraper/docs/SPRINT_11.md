# Sprint 11 — Fiabilité des données

> **Date** : 2026-11-03
> **Statut** : ✅ Terminé (2 points à valider manuellement, cf. 11.5)
> **Origine** : [AUDIT_2026-11.md](AUDIT_2026-11.md) — bugs B1 à B6

## Objectif

Corriger les bugs qui faussent les données stockées : prix mal parsés, statuts
incohérents, géocodage biaisé, URLs de recherche trop restrictives, doublons
non exploités. Périmètre volontairement petit, sans refactor (→ Sprint 12).

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 11.1 | `parse_price` robuste | ✅ | Séparateurs de milliers, décimales, entrée numérique |
| 11.2 | Réactivation + MAJ dans `insert_annonce` | ✅ | Retour `"reactivated"`, compteur dans `main.py` |
| 11.3 | Statut `hidden` au lieu du `DELETE` | ✅ | `set_annonce_status`, route `/restore`, filtre « Masquées » |
| 11.4 | Géocodage fiable | ✅ | `build_queries`, cache négatif 30 j, viewbox, retry |
| 11.5 | URLs de recherche dérivées de la config | ✅ | LBC OK ; SeLoger `priceMax` + types T1/T2 à valider |
| 11.6 | Doublons cohérents et persistés | ✅ | `duplicate_of`, badge « aussi sur … », filtre UI |
| 11.7 | Script de réparation des données existantes | ✅ | Exécuté le 2026-11-03 (9 adresses re-géocodées) |

---

## 11.1 — `parse_price` robuste

**Fichier** : `filters/price_and_distance.py`

Supprimer les séparateurs de milliers **avant** la regex, ignorer les décimales :

```python
_THOUSANDS_SEP = re.compile(r"(?<=\d)[\s  .](?=\d{3}\b)")

def parse_price(price_raw: Optional[str]) -> Optional[int]:
    if not price_raw:
        return None
    if isinstance(price_raw, (int, float)):
        return int(price_raw)
    cleaned = _THOUSANDS_SEP.sub("", price_raw.lower())
    match = re.search(r"\d+", cleaned)      # "450,50" → 450
    return int(match.group()) if match else None
```

- Accepter un `int` en entrée (certains extracteurs le fournissent déjà).
- `MIN_RENT_EUR` reste le garde-fou contre les prix aberrants (« 5 € »).

**Tests** (`tests/test_filters.py`) :

| Entrée | Attendu |
|---|---|
| `"450 €"` | 450 |
| `"1 200 €"` | 1200 |
| `"1 050 € cc"` | 1050 |
| `"1.050 €"` | 1050 |
| `"450,50 €"` | 450 |
| `"5 €"` | 5 |
| `None`, `""`, `"Prix sur demande"` | None |
| `480` (int) | 480 |

---

## 11.2 — Réactivation et mise à jour dans `insert_annonce`

**Fichier** : `storage/sqlite.py::insert_annonce`

Quand l'URL existe déjà :
1. `status = 'active'`, `checked_at = NULL` **si** `status = 'expired'` (pas si `hidden`, cf. 11.3).
2. Mettre à jour `location_raw` et `distance_enac_km` si non nuls et différents.
3. Garder le comportement prix actuel (le Sprint 12.4 ajoutera l'historique).
4. Nouveau code retour `"reactivated"` → compteur dédié dans `main.py`.

Regrouper en un seul `UPDATE` + un seul `commit` :

```sql
UPDATE annonces SET
  scraped_at = :now,
  status = CASE WHEN status = 'expired' THEN 'active' ELSE status END,
  checked_at = CASE WHEN status = 'expired' THEN NULL ELSE checked_at END,
  location_raw = COALESCE(:location_raw, location_raw),
  distance_enac_km = COALESCE(:distance, distance_enac_km),
  photos = COALESCE(photos, :photos)
WHERE url = :url
```

**Tests** (`tests/test_storage.py`) : insert → marquer `expired` → réinsert ⇒ `active` + retour `"reactivated"` ; une annonce `hidden` reste `hidden`.

---

## 11.3 — Statut `hidden` au lieu du `DELETE`

**Fichiers** : `ui.py` (`/delete`), `storage/sqlite.py`, `storage/cleaner.py`

- Nouvelle fonction `set_annonce_status(annonce_id: int, status: str) -> Optional[str]` dans `storage/sqlite.py` (retourne le titre, `None` si introuvable), statuts autorisés : `active`, `expired`, `hidden`.
- `/delete` appelle `set_annonce_status(id, "hidden")` — le bouton ✕ devient « Masquer ».
- UI : `hidden` exclu par défaut ; option « Masquées » dans le filtre statut + bouton « Restaurer ».
- `check_links_playwright` et `get_pending_annonces` ignorent `hidden` (pas de requêtes inutiles).
- `/api/map-data` exclut `hidden` par défaut.

---

## 11.4 — Géocodage fiable

**Fichier** : `geo/distance.py`

1. **Suffixe conditionnel** : ajouter `", Toulouse"` seulement si l'adresse ne contient ni code postal (`\b31\d{3}\b`) ni nom de commune connue. Toujours finir par `", France"`.
   ```python
   def _build_query(address: str) -> str:
       if re.search(r"\b\d{5}\b", address) or any(c.lower() in address.lower() for c in KNOWN_COMMUNES):
           return f"{address}, France"
       return f"{address}, Toulouse, France"
   ```
   `KNOWN_COMMUNES` dans `config.py` (Ramonville-Saint-Agne, Labège, Castanet-Tolosan, Balma, Blagnac, Colomiers, Muret, L'Union…).
2. **Nettoyage** : retirer les suffixes de quartier non géocodables (« Centre-ville », « Proche … ») avant 2ᵉ essai ; en dernier recours, géocoder le seul code postal.
3. **Cache négatif** : en cas d'échec, insérer `(address, NULL, NULL, now)` ; `geocode_address` renvoie `None` sans appel réseau si l'échec date de < 30 jours (`GEOCODE_NEGATIVE_TTL_DAYS`).
4. **Retry** : envelopper l'appel Nominatim avec `utils/retry.py::retry_with_backoff(max_attempts=3, exceptions=(GeocoderTimedOut, GeocoderServiceError))`.
5. **Supprimer `init_db()`** de `geocode_address` : `main.py` l'appelle déjà au démarrage.
6. **Bornage** : `viewbox` autour de Toulouse + `bounded=True` pour éviter les homonymes (ex. « Saint-Agne » ailleurs en France).

**Tests** (`tests/test_geo.py`, Nominatim mocké) : construction de requête, cache hit, cache négatif, expiration du cache négatif.

---

## 11.5 — URLs de recherche dérivées de la config

**Fichier** : `config.py`

Construire les URLs à partir des critères au lieu de les coder en dur :

```python
LEBONCOIN_SEARCH_URL = (
    "https://www.leboncoin.fr/recherche?category=10"
    f"&locations={LEBONCOIN_LOCATION}"
    f"&price={MIN_RENT_EUR}-{MAX_RENT_EUR}"
    "&real_estate_type=2"
    "&sort=time&order=desc"          # plus récentes d'abord (cf. Sprint 13 alertes)
)
```

- SeLoger : ajouter `&maxPrice={MAX_RENT_EUR}`, retirer `classifiedBusiness=Professional`, `estateSubTypes` → studio + T1 + T2 (à valider manuellement dans le navigateur : capturer l'URL après avoir coché les filtres).
- Tri par **date** plutôt que prix : avec `MAX_PAGES_PER_SITE`, on récupère en priorité les nouveautés.
- Supprimer `PROPERTY_TYPES` s'il n'est pas utilisé pour construire les URLs.

**Validation** : un run `--leboncoin` puis `--seloger` ; aucun prix brut > `MAX_RENT_EUR` dans les logs de rejet ; nombre d'annonces brutes ≥ avant.

---

## 11.6 — Doublons cohérents et persistés

**Fichier** : `storage/sqlite.py::find_potential_duplicates`, `main.py`

- Critère unique documenté : **site différent**, prix ±`DUPLICATE_PRICE_TOLERANCE` (config, défaut 5 € — 10 € donnait trop de faux positifs avec le seul critère « 2 mots communs »), surface ±2 m² si connue, ≥ 2 mots communs dans `location_raw`.
- Remplacer `DEDUP_KEYS` (inutilisé) par `DUPLICATE_PRICE_TOLERANCE`.
- Nouvelle colonne `duplicate_of INTEGER` (id de l'annonce la plus ancienne) renseignée dans `main.py` après `insert_annonce`.
- UI : badge « Aussi sur LBC » / lien vers l'autre annonce ; filtre « masquer doublons ».

---

## 11.7 — Script de réparation des données existantes

**Fichier** : `scripts/repair_data.py` (nouveau, idempotent ; simulation par défaut, `--apply` pour écrire après sauvegarde `data/annonces.bak-*.sqlite`)

1. Pour les annonces enrichies dont `description` contient un prix ≥ 1000 : signaler (le prix brut n'est pas stocké → re-scraping nécessaire).
2. Purger les entrées négatives du cache géo puis re-géocoder les annonces avec `distance_enac_km IS NULL`.
3. Calculer `duplicate_of` sur l'existant.

---

## Critères d'acceptation

- [x] Tous les cas de test 11.1 passent.
- [x] Une annonce expirée revue redevient active ; une annonce masquée ne revient jamais.
- [x] Un 2ᵉ run consécutif ne fait **aucun** appel Nominatim pour des adresses déjà en échec.
- [x] Les URLs générées contiennent `MIN_RENT_EUR`/`MAX_RENT_EUR`.
- [x] `pytest` vert : 107 passés, 1 ignoré (contre 73 + 3 échecs avant le sprint).

## Bilan d'implémentation (2026-11-03)

| Fichier | Changement |
|---|---|
| `filters/price_and_distance.py` | `parse_price` : regex `_THOUSANDS_SEP`, accepte `int`/`float` |
| `storage/sqlite.py` | `insert_annonce` (UPDATE unique, réactivation), `find_potential_duplicates` réécrit, `set_duplicate_of`, `set_annonce_status`, `ANNONCE_STATUSES`, migration `duplicate_of` |
| `geo/distance.py` | `build_queries`, `_nominatim` (retry + viewbox), cache négatif, `_ensure_cache_table` au lieu de `init_db()` |
| `config.py` | `KNOWN_COMMUNES`, `GEOCODE_VIEWBOX`, `GEOCODE_NEGATIVE_TTL_DAYS`, `DUPLICATE_PRICE_TOLERANCE` (remplace `DEDUP_KEYS`), URLs dérivées du budget |
| `main.py` | Compteur « Réactivées », rattachement des doublons après insertion |
| `ui.py` | `_build_filters` partagé liste/carte (corrige aussi la requête cassée si `prix_min` non numérique), `/delete` → masquage, `/restore`, filtres « Masquées » et « Doublons », badge « aussi sur … » |
| `scripts/repair_data.py` | Nouveau |
| `tests/` | `test_geo.py`, `test_ui.py` (nouveaux), `test_storage.py` (3 tests obsolètes corrigés + 12 nouveaux), `test_filters.py` |

### Reste à valider manuellement (navigateur)

> **2026-11-14 — abandonné** : le profil ENAC n'est plus développé, seul le profil Blagnac compte. Les points 1 et 2 visent l'URL SeLoger ENAC et ne seront pas faits. Le profil Blagnac utilise des URLs copiées du site (`seloger_search_url`, `lbc_search_url`) et n'est pas concerné.

1. **SeLoger `priceMax`** : nom de paramètre non vérifié. Ouvrir `config.SELOGER_SEARCH_URL` dans Chrome et vérifier que le filtre « Budget max 500 € » est coché. Sinon, capturer l'URL après avoir réglé le budget à la main et corriger le paramètre.
2. **SeLoger types T1/T2** : cocher Studio + T1 + T2 sur le site, copier la valeur de `estateSubTypes` dans `config.py`.
3. **LBC `sort=time`** : vérifier au premier run que les résultats sont triés « Plus récentes ».
