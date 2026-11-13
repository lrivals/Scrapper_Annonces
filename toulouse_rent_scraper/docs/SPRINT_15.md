# Sprint 15 — Fiches détaillées, tri affiné, nouvelles sources

> **Date** : 2026-11-12
> **Statut** : 🔵 En cours — 15.1 et 15.2 livrés, 15.3 → 15.8 planifiés
> **Origine** : réflexion « comment améliorer la récolte, le tri, l'automatisation et la couverture »
> **Prérequis** : [Sprint 12](SPRINT_12.md) (migrations versionnées, `chrome_session`), [Sprint 13](SPRINT_13.md) (score, notifications), [Sprint 14](SPRINT_14.md) (profils)

## Objectif

Passer de fiches « titre, prix, surface » à des **fiches profil complètes et fiables**,
pour trier sur ce qui compte vraiment (coût réel, disponibilité, trajet, confort) et
**détecter tout seul** quand l'extraction se dégrade.

Constat de départ :

1. Les extracteurs de détail lisent le DOM (`data-test-id`) puis font des regex sur
   **tout le texte de la page** : fragile, et certaines valeurs sont fausses
   (« non meublé » comptait comme meublé, `(\d+)\s*pièce` peut matcher une autre annonce
   suggérée en bas de page).
2. La position vient du géocodage du texte « Toulouse 31400 » : centre du code postal,
   pas l'emplacement du bien. La distance — 30 % du score — est donc approximative.
3. Un changement de mise en page d'un site vide silencieusement les fiches.
4. Beaucoup d'informations utiles ne sont que dans la description en texte libre.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 15.1 | LBC : extraction depuis `__NEXT_DATA__`, GPS exact, santé de l'extraction | ✅ | À valider sur une vraie page (voir bilan) |
| 15.2 | LBC : annonces complètes dès la page de recherche | ✅ | À valider sur une vraie page (voir bilan) |
| 15.3 | SeLoger : extraction depuis l'état JSON embarqué | 🔲 | Même principe que 15.1 |
| 15.4 | Analyse de la description par LLM | 🔲 | Disponibilité, APL/Visale, bail, arnaques, résumé |
| 15.5 | Critères éliminatoires par profil | 🔲 | Distincts des poids du score |
| 15.6 | Retours ⭐ / 👎 dans l'UI → poids appris | 🔲 | Régression logistique simple |
| 15.7 | Nouvelle source : Bien'ici (API JSON) | 🔲 | Puis PAP ([Sprint 4](SPRINT_4.md)) |
| 15.8 | Doublons inter-sites par empreinte photo | 🔲 | `imagehash` |

Hors sprint, à garder en tête : temps de trajet (13.5, désormais possible grâce au GPS
exact), suivi des candidatures (contacté → visite → réponse), message de contact
pré-rempli (jamais envoyé automatiquement : CGU des sites, risque de ban).

---

## 15.1 — LeBonCoin : JSON embarqué, GPS exact, santé de l'extraction ✅

**Fichiers** : `scrapers/detail_extractors/lbc_json.py` (nouveau),
`scrapers/detail_extractors/leboncoin_detail.py`, `scrapers/enricher.py`,
`storage/migrations.py`, `storage/sqlite.py`, `storage/quality.py` (nouveau),
`filters/price_and_distance.py`, `pipeline.py`, `scoring.py`, `config.py`, `main.py`,
`ui/templates/index.html`, `ui/static/app.css`, `tests/test_lbc_json.py` (nouveau)

### Extraction

LeBonCoin est une application Next.js : la page d'annonce contient
`<script id="__NEXT_DATA__">` avec l'annonce complète en `props.pageProps.ad`.

Ordre d'extraction dans `leboncoin_detail.extract_detail` :

1. **JSON** (`lbc_json.extract_from_html`) — si l'annonce est trouvée et contient au moins
   la surface, les pièces ou la description, le DOM n'est pas consulté du tout
   (pas de scroll, pas de regex sur la page entière).
2. **Description** — charges et dépôt de garantie, s'ils manquent dans le JSON, sont
   cherchés par regex dans le texte de l'annonce seulement (le gap entre le nombre et le
   mot-clé ne traverse pas une fin de phrase).
3. **DOM** — extraction historique (Sprint 3) si le JSON est absent ; un JSON partiel
   complète alors les champs que le DOM n'a pas trouvés (`extraction_source = "json+dom"`).

`lbc_json` est défensif : plusieurs clés candidates par champ (`ATTRIBUTE_KEYS`),
recherche en largeur de l'annonce si elle n'est pas à l'emplacement attendu, valeurs
« Vierge » / « Non renseigné » → `None`, aucune exception ne remonte.

| Champ | Source JSON | Nouveau ? |
|---|---|---|
| surface, pièces, chambres, étage | `square`, `rooms`, `bedrooms`, `floor_number` | |
| meublé | `furnished` (`1` / `2` + libellé) | corrige « non meublé » |
| DPE / **GES** | `energy_rate`, `ges` | GES ✨ |
| **ascenseur** | `elevator` | ✨ |
| **charges comprises** | `charges_included` | ✨ |
| charges, caution | `monthly_charges`, `security_deposit`… sinon description | |
| photos | `images.urls_large` (dédoublonnées) | toutes les photos, sans scroll |
| annonceur, date | `owner.type`, `first_publication_date` | |
| **lat / lon** | `location.lat/lng` (+ `is_shape`, `source`) | ✨ |
| **attributs bruts** | tous les `attributes` | ✨ `extra_attributes` (JSON) |

`extra_attributes` garde tous les attributs du site : un champ découvert plus tard
(parking, chauffage, extérieur…) s'exploite sans re-scraper.

### Coordonnées exactes

- Migration 4 : colonnes `geo_precision` (`exact` | `approx`), `ges_rating`, `elevator`,
  `charges_included`, `extraction_source`, `field_sources`, `extra_attributes`.
  Les coordonnées existantes (géocodage) sont marquées `approx`.
- `update_annonce_enrichment` : un point **exact** remplace le géocodage ; un point
  `approx` (`is_shape` ou `source = city`) ne sert que si l'annonce n'avait aucune position.
- Après enrichissement, `enricher._refresh_distances` recalcule `distance_enac_km` et la
  distance de **chaque profil déjà rattaché** ; le rescore final en tient compte.
- Aux scrapings suivants, `pipeline.process_annonces` passe le point exact connu à
  `match_profiles(known_coords=…)` : plus de géocodage, et la distance reste la bonne.

### Score

`rent_cc` n'ajoute plus les charges quand l'annonce est marquée **charges comprises**
(évite de compter deux fois les charges d'un loyer CC).

### Santé de l'extraction

- `storage/quality.py` : taux de remplissage par site et par champ, part d'annonces lues
  depuis le JSON.
- Fin de chaque `enrich` : si, sur ≥ `QUALITY_MIN_SAMPLES` (5) annonces d'un site, un champ
  clé (`QUALITY_MIN_FILL_RATES` : surface, pièces, description, photos — 60 %) ou la part
  JSON de LBC (`QUALITY_MIN_JSON_RATE` — 50 %) passe sous son seuil → warning dans les logs
  **et notification** ntfy/Telegram « Extraction dégradée — sélecteurs à vérifier ».
- Nouvelle commande :
  ```bash
  python main.py quality            # toutes les annonces enrichies
  python main.py quality --days 7   # enrichies cette semaine
  ```
  Sortie (chiffres d'exemple) :
  ```
  site       n  JSON  surface  pièces  chambres  étage  descr.  photos  …  GPS exact
  ---------  -  ----  -------  ------  --------  -----  ------  ------     ---------
  LeBonCoin  42  95%      98%     97%       60%    55%    100%    100%  …        71%
  ```

### UI

Pastilles sous chaque carte : `T2`, `DPE D`, `GES B`, `Meublé` / `Vide`, `CC` ou
`+40 € ch.`, `Ét. 3` / `RDC`, `Ascenseur`, `📍 GPS` (position exacte).

### Bilan

- Tests : `tests/test_lbc_json.py` (27 tests : parsing, repli DOM, stockage des
  coordonnées, recalcul des distances, score CC, alertes, CLI, UI). Suite complète verte.
- ⚠️ **Validation manuelle à faire** : la structure du JSON a été écrite d'après la forme
  connue des pages LBC, sans capture réelle (réseau de développement bloqué par le site).
  Au prochain run local :
  1. `python main.py enrich --site leboncoin --limit 5`
  2. `python main.py quality` → la colonne **JSON** doit être proche de 100 % pour LBC ;
  3. si un champ reste vide, regarder `extra_attributes` d'une annonce en base pour la
     vraie clé et l'ajouter dans `ATTRIBUTE_KEYS` (`lbc_json.py`) ;
  4. vérifier sur 2–3 annonces que `is_shape` / `source` distinguent bien les adresses
     précises des positions approximatives.
- Pour re-traiter les annonces déjà enrichies par le DOM :
  `UPDATE annonces SET enrichment_status = 'pending', enrichment_attempts = 0 WHERE site = 'LeBonCoin';`
  puis `python main.py enrich --site leboncoin`.

---

## 15.2 — LBC : annonces complètes dès la page de recherche ✅

**Fichiers** : `scrapers/detail_extractors/lbc_json.py`, `scrapers/base.py`,
`scrapers/leboncoin.py`, `pipeline.py`, `filters/price_and_distance.py`,
`storage/sqlite.py`, `storage/quality.py`, `notify/messages.py`, `config.py`,
`tests/test_lbc_search_json.py` (nouveau)

La page de résultats est elle aussi rendue par Next.js : `__NEXT_DATA__` contient les
annonces de la page (`props.pageProps.searchData.ads`, sinon la plus longue liste
d'objets « annonce » trouvée dans l'arbre), au même format que la page de détail.

### Scraping

- `lbc_json.search_annonces_from_html` : chaque annonce → annonce brute du pipeline
  (titre, prix, `location.city_label`, URL, 1ʳᵉ photo, `nb_rooms` pour le filtre pièces,
  lat/lon/précision) + `details` (tous les champs de 15.1, `extraction_source = "search_json"`).
- `BaseScraper._scrape_current_page` (nouveau crochet `page_json_annonces`, défaut : aucun) :
  1. lit le JSON de la page ;
  2. **vérifie qu'il correspond aux cartes affichées** : au moins 50 % des cartes
     (jointure par `list_id` extrait de l'URL) doivent y figurer. Sinon le JSON est ignoré —
     cas de la pagination par bouton « suivant », où Next.js ne met pas `__NEXT_DATA__` à jour ;
  3. ajoute les annonces du JSON, puis extrait par le DOM **uniquement les cartes absentes
     du JSON** (plus de scroll carte par carte pour celles-là) ;
  4. sans JSON exploitable : extraction par cartes comme avant.

### Pipeline

- Le point GPS **exact** de l'annonce sert directement au filtre de rayon (plus de géocodage
  Nominatim pour ces annonces) ; un point **approximatif** sert de secours si le géocodage de
  l'adresse échoue.
- `details` est enregistré à l'insertion, **sauf si l'annonce est déjà enrichie** (une fiche
  de page de détail n'est jamais écrasée par la recherche).
- Fiche complète (description + surface) → `enrichment_status = 'done'` : **pas de visite
  de la page de détail**. Sinon les champs sont pré-remplis et l'annonce reste `pending`.
  `LBC_SEARCH_JSON_SKIPS_DETAIL = False` (config) garde toujours la visite.
- Notifications : `T2 38 m² DPE D` dans chaque ligne, dès la première détection.
- Compteur `Fiches pré-remplies depuis la recherche` dans le résumé du run.

### Santé

- `search_health_rows` + `report_extraction_health` en fin de `run_scraping` : même alerte
  qu'à l'enrichissement (champs clés < 60 %, ou moins de 50 % d'annonces LBC lues depuis le
  JSON). Une recherche LBC qui retombe sur les cartes DOM déclenche donc l'alerte.
- `quality` compte `search_json` comme une lecture JSON.

### Bilan

- Tests : `tests/test_lbc_search_json.py` (23 tests : parsing de la recherche, jointure
  JSON ↔ cartes, JSON périmé, repli DOM, option de visite, stockage, non-écrasement,
  GPS approximatif de secours, santé, notification). Suite complète verte.
- ⚠️ **Validation manuelle à faire** (réseau de développement bloqué par LBC) :
  1. `python main.py scrape --site leboncoin --profile blagnac` → le log doit afficher
     `N annonces lues depuis le JSON de la page` sur chaque page ;
  2. `python main.py quality --days 1` → JSON ≈ 100 %, description et surface remplies ;
  3. vérifier sur 2–3 annonces que la description de la recherche est **complète**
     (et non tronquée) : sinon passer `LBC_SEARCH_JSON_SKIPS_DETAIL = False` ;
  4. si le log dit `JSON ignoré : 0 % des cartes…` sur la page 1, le chemin des annonces
     a changé : capturer la page avec `python scripts/debug/capture_cards_leboncoin.py`
     (→ `logs/debug_lbc_fullpage.html`), chercher `__NEXT_DATA__` et ajuster `find_search_ads`.

## 15.3 — SeLoger : état JSON embarqué 🔲

SeLoger embarque aussi l'état de la page dans un `<script>` (à identifier avec
`scripts/debug/explore_seloger_structure.py`). Même architecture que 15.1 :
`seloger_json.py` + repli DOM + `extraction_source`. Seuil `QUALITY_MIN_JSON_RATE["SeLoger"]`
à ajouter une fois validé.

## 15.4 — Analyse de la description par LLM 🔲

Extraction structurée (sortie JSON imposée) sur la description, pendant l'enrichissement,
avec un petit modèle peu coûteux (≈ quelques centimes pour quelques centaines d'annonces) :

| Champ | Exemple dans le texte |
|---|---|
| `available_from` | « libre au 1er décembre » |
| `lease_type` | bail mobilité / étudiant / colocation / classique |
| `apl_ok`, `visale_ok` | « APL possible », « garant Visale accepté » |
| `parking`, `outdoor`, `heating` | « place de parking en sus 50 € », « balcon », « chauffage collectif gaz » |
| `agency_fees` | « honoraires 350 € » |
| `summary` | résumé en 2 lignes pour la carte |
| `scam_flags` | « je suis à l'étranger », paiement avant visite, prix ≪ médiane €/m² |

Clé d'API dans `.env` ; désactivé par défaut ; résultat mis en cache par annonce (le texte
ne change pas). Les signaux d'arnaque donnent un malus de score et une pastille ⚠️.

## 15.5 — Critères éliminatoires par profil 🔲

`SearchProfile.requirements` : ex. `available_before`, `apl_required`, `no_ground_floor`,
`min_surface_m2`. Une annonce qui ne les respecte pas est masquée du profil (statut par
profil, réversible) au lieu d'être seulement moins bien notée. Inconnu = conservé.

## 15.6 — Retours ⭐ / 👎 et poids appris 🔲

- UI : boutons ⭐ favori / 📞 contacté / 👎 pas intéressé (table `annonce_feedback`).
- Après ~30 retours : régression logistique sur les critères 0–1 du score
  (`score_detail`) → poids proposés, affichés à côté des poids actuels, appliqués sur
  confirmation (`rescore`).
- Bonus : notification si une annonce ⭐ baisse de prix ou disparaît.

## 15.7 — Nouvelle source : Bien'ici 🔲

Bien'ici agrège un grand nombre d'agences et son interface consomme une API JSON
(`realEstateAds.json?filters=…`) qui renvoie surface, pièces, DPE, charges, photos et
position. Scraper sans navigateur (requests), donc à côté de `BaseScraper` :

- introduire un modèle commun `Listing` (dataclass) que chaque source produit ;
- deux familles de sources : **API JSON** (Bien'ici, puis PAP) et **navigateur + anti-bot**
  (LBC, SeLoger) ;
- rythme raisonnable (une requête par page de résultats, pauses), usage personnel.

Ensuite : PAP ([Sprint 4](SPRINT_4.md)), Logic-Immo (même groupe que SeLoger), et pour le
profil ENAC Lokaviz (CROUS) / Studapart.

## 15.8 — Doublons inter-sites par empreinte photo 🔲

Hash perceptuel (`imagehash.phash`) de la première photo, stocké en base ; deux annonces
de sites différents avec une distance de Hamming ≤ 6 et un prix proche → `duplicate_of`.
Complète la détection actuelle (prix + mots de la localisation).
