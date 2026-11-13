# Sprint 15 — Fiches détaillées, tri affiné, nouvelles sources

> **Date** : 2026-11-12
> **Statut** : 🔵 En cours — 15.1, 15.2, 15.4 à 15.8 livrés ; reste 15.3 (SeLoger, nécessite une capture réelle)
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
| 15.4 | Analyse de la description par LLM | ✅ | Optionnelle ; LLM et clé de l'utilisateur ; une seule lecture par texte (15.4-bis) |
| 15.5 | Critères éliminatoires par profil | ✅ | Distincts des poids du score ; à remplir par profil |
| 15.6 | Retours ⭐ / 👎 dans l'UI → poids appris | ✅ | Régression logistique ; appliqués sur confirmation |
| 15.7 | Nouvelle source : Bien'ici (API JSON) + modèle `Listing` | ✅ | À valider sur la vraie API (voir bilan) ; puis PAP ([Sprint 4](SPRINT_4.md)) |
| 15.8 | Doublons inter-sites par empreinte photo | ✅ | dHash avec Pillow (sans `imagehash`) |

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
- **Validation réelle du 2026-11-13** (`enrich --site leboncoin --limit 5` puis `quality --days 1`) :
  5/5 enrichies depuis le JSON (`json`), JSON 100 %, surface / pièces / chambres / description /
  photos / charges / caution / meublé / date 100 %, étage / DPE / GES 80 %, annonceur 60 %,
  GPS exact 20 % (1 annonce repositionnée). Aucun champ sous son seuil. ✅
  - 🐛 Corrigé au passage : le premier essai avait marqué les 5 annonces **retirées** alors
    qu'elles étaient en ligne. `is_expired_content` cherchait ses motifs dans le HTML complet,
    et les pages LBC embarquent dans leurs scripts « annonce introuvable », « page introuvable »,
    « annonce supprimée »… Nouveau `page_shows_expired(page)` (`storage/cleaner.py`) : une page
    dont le JSON contient l'annonce est en ligne, sinon seul le texte visible compte. Utilisé
    par `enrich` **et** `check-links` (même défaut). Tests de régression dans `test_enricher.py`
    et `test_cleaner.py`.
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
- **Validation réelle du 2026-11-13** (profil Blagnac, 11 pages, 370 annonces brutes) :
  - ✅ `35 annonces lues depuis le JSON de la page` sur chaque page, 2–5 cartes par page
    complétées depuis le DOM ; 212 fiches pré-remplies.
  - ✅ En base (211 fiches `search_json`) : surface 100 %, photos 98 %, GPS exact 40 %,
    `extra_attributes` complet (meublé, DPE/GES, charges, caution, disponibilité…).
  - ❌ **Aucune description** : le JSON de recherche LBC ne contient pas `body`. Les fiches
    restent donc `pending` et `enrich` visite toujours la page de détail — l'économie visée
    par 15.2 ne joue pas pour LBC (`LBC_SEARCH_JSON_SKIPS_DETAIL` est sans effet).
  - 🐛 Corrigé : le contrôle de santé de la recherche exigeait 60 % de descriptions → alerte
    « Extraction dégradée » (notification haute priorité) à chaque scrape. La description n'est
    plus jugée sur la recherche LBC (`QUALITY_SEARCH_SKIP_FIELDS` dans `config.py`) ; elle
    reste contrôlée après `enrich`. Test : `test_search_health_ignores_description_absent_from_search_json`.

## 15.3 — SeLoger : état JSON embarqué 🔲

SeLoger embarque aussi l'état de la page dans un `<script>` (à identifier avec
`scripts/debug/explore_seloger_structure.py`). Même architecture que 15.1 :
`seloger_json.py` + repli DOM + `extraction_source`. Seuil `QUALITY_MIN_JSON_RATE["SeLoger"]`
à ajouter une fois validé.

## 15.4 — Analyse de la description par LLM ✅

**Fichiers** : `analysis/llm.py` (nouveau), `storage/migrations.py`, `storage/sqlite.py`,
`scoring.py`, `pipeline.py`, `scrapers/enricher.py`, `notify/messages.py`, `main.py`,
`ui/__init__.py`, `ui/templates/index.html`, `ui/static/app.css`, `config.py`,
`requirements.txt`, `.env.example`, `tests/test_llm.py` (nouveau)

### Principe

Chaque description est envoyée **une seule fois** à Claude (SDK officiel `anthropic`) avec une
**sortie JSON imposée** (structured outputs, `output_config.format`) : tous les champs sont
présents, `null` quand l'annonce ne dit rien. Le résultat est stocké en base ; il n'est
recalculé que si le titre, le prix ou la description changent (empreinte `llm_input_hash`,
qui inclut `PROMPT_VERSION` : changer le prompt force la ré-analyse).

| Champ extrait | Colonne | Utilisation |
|---|---|---|
| Résumé (2 phrases) | `summary` | Sous le titre de la carte |
| Disponibilité (date ou « immédiate ») | `available_from` | Pastille, notification ; base de 15.5 |
| Type de bail (classique, meublé, mobilité, étudiant, colocation, saisonnier), colocation | `lease_type`, `colocation` | Pastille |
| APL / Visale acceptées ou refusées | `apl_ok`, `visale_ok` | Pastilles ✓ / ✗ |
| Honoraires d'agence | `agency_fees` | Pastille |
| Charges, dépôt de garantie | `charges`, `deposit` | **Complètent** les colonnes vides (jamais d'écrasement) |
| Parking, extérieur, chauffage, garant exigé | `llm_data` (JSON complet) | Pour 15.5 / 15.6 |
| Signaux d'arnaque + niveau (faible / moyen / élevé) | `scam_flags`, `scam_risk` | Pastille ⚠️, malus de score |

### Arnaques

- Le prompt décrit les arnaques courantes à la location (propriétaire à l'étranger, paiement
  avant visite, Western Union / mandat cash, clés par courrier, plateforme « de réservation »
  tierce, pièces d'identité dès le premier contact, urgence artificielle).
- **Signal local, sans LLM** : prix au m² < 50 % de la médiane des annonces actives
  (`SCAM_LOW_PRICE_RATIO`, médiane calculée sur ≥ 5 annonces) → signal « prix très bas » et
  risque relevé à « moyen » au minimum.
- **Score** : risque moyen × 0,8, élevé × 0,5 (`SCAM_RISK_PENALTY`) ; le malus apparaît dans
  l'infobulle du score. L'analyse tourne avant le recalcul des scores et les notifications, donc
  une annonce suspecte passe sous `NOTIFY_MIN_SCORE` et ne déclenche plus d'alerte.
- UI : pastille « ⚠️ À vérifier » (moyen) ou « ⚠️ Arnaque ? » (élevé), signaux en infobulle ;
  notifications préfixées ⚠️ pour un risque élevé.

### Requête (Claude)

- Effort `LLM_EFFORT = "low"` (extraction simple), `max_tokens` 4000, sortie JSON imposée.
- Prompt système fixe + `cache_control` : identique pour toutes les annonces. La date du jour
  (pour résoudre « libre au 1er décembre ») est dans le message utilisateur.
- Le texte de l'annonce est encadré par `<annonce>` et le prompt précise que c'est une donnée à
  analyser : une description qui contient des consignes ne les fait pas suivre.
- Repli serveur en cas de refus à tort des filtres de sécurité (`fallbacks: "default"`) pour les
  modèles Claude qui l'acceptent.

Fournisseurs, garde-fous de dépense et erreurs : voir **15.4-bis** ci-dessous.

### Bilan

- Tests : `tests/test_llm.py` (backends simulés, aucun appel réel). Un bug trouvé par les tests
  a été corrigé avant livraison (une erreur 400 arrêtait tout le run au lieu de la seule annonce).
- ⚠️ **À valider avec une vraie clé** : `python main.py analyze --limit 5`, relire les 5 fiches dans
  l'UI contre le texte des annonces, vérifier qu'une annonce d'agence ordinaire reste en risque
  « faible », puis `python main.py analyze --stats` pour le coût réel en jetons.

## 15.4-bis — Une seule lecture par texte, LLM au choix de l'utilisateur ✅

**Fichiers** : `analysis/providers.py`, `ui/llm_settings.py`, `ui/templates/llm_settings.html`
(nouveaux), `analysis/llm.py`, `storage/migrations.py` (migration 6), `storage/sqlite.py`,
`main.py`, `config.py`, `ui/__init__.py`, `ui/templates/index.html`, `ui/static/app.css`,
`.env.example`, `tests/test_llm.py`

### Une seule lecture par texte

Registre `llm_analyses` : **une ligne par texte de description** (empreinte SHA-256 du texte
normalisé — espaces et casse ignorés), avec le résultat, le nombre d'appels et les jetons.

| Situation | Avant (15.4) | Maintenant |
|---|---|---|
| Prix ou description modifiés | Relecture | **Pas de relecture** (résultat conservé) |
| Même texte sur une autre URL (republication LBC, autre site) | Relecture | Résultat **réutilisé**, sans appel |
| Doublon inter-sites (`duplicate_of`) au texte différent | Relecture | Analyse de l'original **réutilisée** ; le doublon attend si l'original n'est pas encore lu |
| Analyse en erreur | Retentée à chaque run | **Jamais** automatiquement ; `analyze --retry-errors` la relance **une fois** (`LLM_MAX_CALLS_PER_TEXT = 2`) |
| Refus du modèle | Pas retenté | Pas retenté, même avec `--retry-errors` |
| Changement de prompt, de modèle ou de fournisseur | Relecture (`PROMPT_VERSION`) | **Pas de relecture** |
| `--force` (tout relire) | Disponible | **Supprimé** |
| Deux runs simultanés (UI + timer) | Double lecture possible | Texte **réservé avant l'appel** (insertion atomique) : un seul paie |
| Service indisponible (clé, quota, panne) | Rien marqué | Réservation annulée (rien n'a été facturé), reprise au run suivant |
| Bug ou runs rapprochés | Plafond par run seulement | + **plafond quotidien** `LLM_MAX_CALLS_PER_DAY = 150` |

- Les analyses déjà faites en 15.4 sont reprises dans le registre par la migration 6 : elles ne
  seront jamais relues.
- `python main.py analyze --stats` (et la page « Connexion LLM ») : textes lus, appels
  facturables, relances, annonces couvertes, jetons consommés.
- Conséquence assumée : si une annonce change vraiment de texte, l'analyse reste celle du premier
  texte. Une description tronquée d'abord (recherche LBC), complète ensuite (page de détail) n'est
  donc pas relue — `LBC_SEARCH_JSON_SKIPS_DETAIL` limite ce cas aux fiches jugées complètes.

### LLM et clé de l'utilisateur

- `analysis/providers.py` : deux familles d'API.
  - **Claude** (SDK officiel `anthropic`) — modèle par défaut `claude-opus-5-5`.
  - **Compatibles OpenAI** (`/chat/completions`, appelées en HTTP) : OpenAI, Mistral, OpenRouter,
    Groq, **Ollama** et **LM Studio en local (gratuits, sans clé)**, ou toute autre URL compatible.
    Le modèle est à renseigner (les catalogues changent trop vite pour figer un défaut). Sortie
    `json_schema` stricte ; si le serveur ne la gère pas (400 sur `response_format`, non facturé),
    bascule en `json_object` avec le schéma dans le prompt.
- **Page « Connexion LLM »** (`/settings/llm`, lien dans l'en-tête) : fournisseur, modèle, URL,
  clé, analyse automatique ; bouton « Tester la connexion » (un appel d'essai sur une annonce
  fictive, sur la clé de l'utilisateur) ; « Supprimer la clé » ; statistiques du registre.
- Stockage : `data/llm_settings.json` (dossier ignoré par git), **permissions 600**, prioritaire sur
  le `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_ANALYSIS`).
- **Aucune clé implicite** : la clé est toujours passée explicitement au SDK, qui ne lit donc ni
  `ANTHROPIC_API_KEY` ni un profil `ant` de la machine. Sans fournisseur configuré, aucune
  analyse — même la commande `analyze` s'arrête sans appel.
- Sécurité de la clé : jamais réaffichée (`••••ABCD`), jamais écrite dans les logs ; un champ laissé
  vide garde la clé enregistrée **seulement pour le même fournisseur et la même URL** — elle n'est
  jamais envoyée à un autre service ; formulaires protégés par le jeton CSRF existant ; URL
  limitée à `http(s)://`.
- Limite : l'interface n'a pas de comptes utilisateurs. Une installation = une configuration ; si
  plusieurs personnes partagent la même instance, elles partagent la clé enregistrée.

### Bilan

- Tests : `tests/test_llm.py` (61 tests) — garanties de lecture unique (second run sans appel,
  changement de prix/texte, republication, doublon, erreur non retentée, relance unique, refus,
  service indisponible, réservation concurrente sur 5 threads, texte en cours ailleurs, plafonds
  par run et par jour, aucun fournisseur), migration des analyses existantes, réglages (aucune clé
  implicite, priorité UI/.env, fichier 600), backends Claude et compatibles OpenAI (requête,
  erreurs HTTP, repli `json_object`, refus, troncature, JSON entouré de ```), page de réglages
  (clé jamais affichée, clé non transmise à un autre fournisseur, CSRF, test, suppression, URL
  invalide), CLI `--stats`. Suite complète verte.
- ⚠️ À valider en réel : une connexion par famille (Claude et, par exemple, Ollama local) avec
  « Tester la connexion », puis `analyze --limit 5` et `analyze --stats`.

## 15.5 — Critères éliminatoires par profil ✅

**Fichiers** : `filters/requirements.py` (nouveau), `config.py`, `storage/migrations.py`
(migration 7), `storage/sqlite.py`, `storage/queries.py`, `scoring.py`, `reporting/generator.py`,
`ui/routes.py`, `ui/templates/index.html`, `ui/static/app.css`, `tests/test_requirements.py` (nouveau)

### Principe

Le score classe ; les critères **trient**. `SearchProfile.requirements` (`config.Requirements`) :

| Critère | Exclut si… | Source de la donnée |
|---|---|---|
| `available_before="AAAA-MM-JJ"` | disponible après cette date (« immédiate » passe) | LLM (15.4) |
| `apl_required=True` | l'annonce refuse les APL | LLM |
| `no_ground_floor=True` | étage = 0 | JSON / DOM |
| `min_surface_m2` | surface inférieure | JSON / DOM |
| `furnished=True / False` | meublé ≠ exigé (seulement après enrichissement) | JSON / DOM |
| `no_colocation=True` | colocation | LLM |
| `excluded_lease_types=(…)` | type de bail listé (`saisonnier`, `mobilite`…) | LLM |
| `max_dpe="E"` | DPE plus mauvais | JSON / DOM |

**Inconnu = conservé** : une valeur absente (pas encore enrichie, pas analysée, « NS ») n'exclut
jamais. Le « meublé » d'une annonce non enrichie est ignoré (valeur par défaut des cartes).

### Stockage et calcul

- Migration 7 : `annonce_profiles.excluded_reasons` (NULL = conservée, JSON des motifs sinon) —
  **par profil** : un rez-de-chaussée peut être exclu d'ENAC et rester dans Blagnac.
- Calculé dans `rescore`, donc après l'enrichissement et l'analyse LLM, et **réversible** :
  assouplir un critère puis `python main.py rescore` réintègre les annonces. Le masquage manuel
  (`status = 'hidden'`) reste indépendant.
- Exclues : pas de notification (`annonces_for_notification`), pas dans les rapports Markdown.
  Le score reste calculé (utile pour 15.6).

### UI

- Bandeau « Critères ENAC : APL acceptées · pas de rez-de-chaussée — **N annonces exclues** » (lien).
- Filtre « Critères » : Respectés (défaut) / Tout afficher / Exclues seulement ; aussi sur la carte.
- Motif sur la carte d'une annonce exclue : pastille ⛔ « rez-de-chaussée · APL refusées ».
- Profil sans critère : ni bandeau ni filtre.

### Bilan

- Tests : `tests/test_requirements.py` (33 tests : chaque règle, valeurs inconnues, meublé avant
  enrichissement, migration, exclusion par profil, réversibilité, champs LLM, notifications, UI,
  carte). Suite complète verte.
- **À faire par l'utilisateur** : les profils ENAC et Blagnac n'ont pas encore de critères
  (`Requirements()` vide, aucun effet). Les renseigner dans `config.py`, puis `python main.py rescore`.
- Les critères issus de la description (disponibilité, APL, colocation, bail) ne jouent que si
  l'analyse LLM (15.4) est activée.

## 15.6 — Retours ⭐ / 👎 et poids appris ✅

**Fichiers** : `storage/feedback.py`, `analysis/weights.py`, `ui/templates/weights.html` (nouveaux),
`config.py`, `storage/migrations.py` (migration 8), `storage/sqlite.py`, `storage/queries.py`,
`storage/cleaner.py`, `scoring.py`, `scrapers/enricher.py`, `notify/__init__.py`,
`notify/messages.py`, `main.py`, `ui/routes.py`, `ui/templates/index.html`, `ui/static/app.js`,
`ui/static/app.css`, `tests/conftest.py`, `tests/test_feedback.py` (nouveau)

### Retours dans l'interface

- Trois boutons sur chaque carte : ⭐ favori, 📞 contacté, 👎 pas intéressé. Un seul actif à la
  fois ; re-cliquer l'efface. Requête AJAX (`POST /feedback`, jeton CSRF), pas de rechargement.
- Table `annonce_feedback` (migration 8) : **par profil** (une annonce peut être ⭐ pour Blagnac et
  👎 pour l'ENAC), avec le prix au moment du retour.
- 👎 sort l'annonce de la liste par défaut (la carte disparaît aussitôt) ; filtre « Retours » :
  sans les 👎 (défaut) / ⭐ / 📞 / 👎 / tout. Différent du masquage 🗑 : 👎 sert d'exemple à
  l'apprentissage et ne vaut que pour le profil.

### Poids appris

- `analysis/weights.py` : régression logistique en pur Python (descente de gradient, L2 = 0,05) sur
  les critères 0–1 du score (`score_detail`) — ⭐ et 📞 = intéressant, 👎 = pas intéressé.
  Les critères étant sur la même échelle, les coefficients se comparent directement : négatifs
  ramenés à 0, puis normalisés à la somme des poids actuels (100).
- Proposition seulement à partir de **30 retours** (`FEEDBACK_MIN_SAMPLES`) dont **5 de chaque
  sorte** (`FEEDBACK_MIN_PER_CLASS`) ; sinon le message dit ce qui manque. Aucun critère
  explicatif (tous les coefficients ≤ 0) → poids conservés.
- Affichage à côté des poids actuels, avec la concordance avec les retours et la référence
  « toujours la même réponse » (un écart faible = les critères du score expliquent mal les choix).
- **Appliqués sur confirmation seulement**, puis `rescore` : page « Poids du score »
  (`/settings/weights`) ou CLI. Stockés dans `data/score_weights.json` (prioritaire sur
  `SCORE_WEIGHTS`, ignoré s'il est illisible ou incomplet) ; « Revenir aux poids par défaut »
  le supprime.
  ```bash
  python main.py weights           # poids actuels vs proposés
  python main.py weights --apply   # confirmer et recalculer les scores
  python main.py weights --reset   # revenir à config.py
  ```

### Suivi des favoris (bonus)

- Baisse de prix d'un ⭐ : notifiée **quel que soit le score** (et même si l'annonce est exclue par
  les critères 15.5), titre « ⭐ Baisse de … », priorité haute.
- ⭐ devenu indisponible (`check-links`, `purge`, ou détecté à l'enrichissement) : notification
  « ⭐ Favori retiré ». Une erreur de notification n'interrompt jamais la vérification.
- Un 👎 n'est jamais notifié (ni nouvelle annonce, ni baisse de prix).

### Bilan

- Tests : `tests/test_feedback.py` (33 tests : stockage par profil, bascule, régression sur données
  synthétiques — le critère qui explique les retours ressort en tête —, seuils, cas sans signal,
  fichier de poids invalide, effet sur le score, notifications ⭐ / 👎, favori retiré, purge, UI,
  CSRF, filtres, page des poids, CLI). Le fichier de poids des tests est toujours temporaire.
  Suite complète verte.
- À l'usage : donner ~30 avis (dont au moins 5 👎) sur un ou deux profils, puis
  `python main.py weights`. Les retours de tous les profils servent à un seul jeu de poids.

## 15.7 — Nouvelle source : Bien'ici ✅

**Fichiers** : `scrapers/listing.py`, `scrapers/api_base.py`, `scrapers/bienici.py` (nouveaux),
`scrapers/__init__.py`, `scrapers/base.py`, `scrapers/detail_extractors/lbc_json.py`,
`config.py`, `pipeline.py`, `tests/test_bienici.py` (nouveau), README

Bien'ici agrège un grand nombre d'agences ; son site consomme une API JSON qui renvoie des
annonces complètes. Pas de navigateur, pas de DataDome.

### Modèle commun `Listing`

`scrapers/listing.py` : dataclass d'annonce (prix, position + précision, surface, pièces,
DPE/GES, charges, photos, description…). `to_annonce()` produit le format historique du
pipeline + `details` (champs d'enrichissement) + `lat/lon/geo_precision` + `nb_rooms`.
`details.enrichment_status = "done"` si l'annonce est complète (description + surface) ou si
la source fait foi (`authoritative`, cas d'une API).
La recherche LBC (15.2) produit désormais aussi des `Listing` (`search_ad_to_listing`) :
un seul format de sortie pour toutes les sources JSON. Les cartes DOM restent des dicts.

### Deux familles de sources

| Famille | Base | Sites | Particularités |
|---|---|---|---|
| Navigateur + anti-bot | `BaseScraper` | SeLoger, LeBonCoin | Chrome, warm-up, captcha, `requires_cooldown = True` |
| API JSON | `ApiScraper` (`api_base.py`) | Bien'ici (puis PAP…) | `requests`, pause polie entre requêtes, `requires_cooldown = False` |

`ApiScraper` : session HTTP avec User-Agent de navigateur, `get_json` (403/429 →
`ApiBlocked` → `record_block` : le site est sauté par les runs planifiés pendant le cooldown
anti-ban habituel), résultats ajoutés page par page (une erreur en page 3 garde les pages 1–2).
`run_scraping` ne fait plus la pause de 60–120 s avant une source API.

### Bien'ici

- **Recherche** : `GET realEstateAds.json?filters={…}` — `filterType: rent`, types de bien du
  profil, budget (`minPrice`/`maxPrice`), pièces (`minRooms`/`maxRooms`), zones, tri par date
  de publication décroissante ; 50 annonces par page, 4 pages max (`BIENICI_*` dans `config.py`).
- **Zones** : `SearchProfile.bienici_places` (communes) résolues via l'autocomplétion du site
  (`res.bienici.com/suggest.json?q=…`, nom exact sinon 1ʳᵉ suggestion), cache
  `data/bienici_zones.json`. `bienici_zone_ids` permet de forcer des identifiants.
  ENAC : Toulouse + 6 communes du sud-est ; Blagnac : Blagnac, Toulouse + 5 communes, maisons
  incluses (`bienici_property_types = ("flat", "house")`). Le rayon exact reste filtré en local.
- **Annonce** → `Listing` : surface, pièces, chambres, étage, ascenseur, meublé, DPE/GES
  (« NS »/« VI » → inconnu), charges, dépôt de garantie, photos, annonceur, date, description
  (HTML nettoyé), position `blurInfo` (`type: exact` → exacte, sinon centre de zone floutée →
  approximative), et dans `extra_attributes` : honoraires, date de disponibilité, balcon,
  terrasse, parking, chauffage…
- **Charges comprises** : par défaut oui (affichage du loyer CC obligatoire, loi ALUR) ; un
  indicateur explicite de l'API (`isPriceIncludingCharges`…) prime.
- **URL** : `/annonce/location/<commune>/<type>/<n>pieces/<id>`, sinon `/annonce/<id>`.
- Annonces marquées enrichies d'emblée (`extraction_source = "api"`) : jamais de visite.

### Pipeline

- Doublons inter-sites : la surface des annonces JSON (dans `details`) est maintenant transmise
  à `find_potential_duplicates` → un T2 publié sur LBC et Bien'ici est rattaché, un bien de
  même prix mais de surface différente ne l'est pas.
- `--site bienici` dans la CLI ; « Bien'ici » apparaît dans le filtre de sites de l'UI.

### Bilan

- Tests : `tests/test_bienici.py` (21 tests : conversion, valeurs atypiques, `Listing`, filtres,
  zones et cache, pagination, blocage, format inattendu, pipeline, doublon inter-sites, pas de
  pause avant une API, CLI). Suite complète verte.
- ⚠️ **Validation manuelle à faire** (réseau de développement sans accès à bienici.com) :
  1. `python main.py scrape --site bienici --profile enac` → `bienici.log` doit montrer des
     pages d'annonces ; `data/bienici_zones.json` doit contenir une zone par commune ;
  2. ouvrir 2–3 annonces depuis l'UI : **le lien doit mener à la bonne page** (sinon ajuster
     `ad_url`) ;
  3. vérifier sur une annonce que le prix affiché par Bien'ici est bien charges comprises ;
  4. `python main.py quality` → colonne JSON à 100 % pour Bien'ici, surface/photos remplies ;
  5. si l'API répond 400 : un nom de filtre a changé — comparer avec la requête
     `realEstateAds.json` visible dans l'onglet Réseau du navigateur sur bienici.com.
- Annonces retirées : `check-links` utilise les marqueurs génériques (« annonce n'est plus
  disponible »…) ; à confirmer sur une annonce Bien'ici expirée.

## 15.8 — Doublons inter-sites par empreinte photo ✅

**Fichiers** : `filters/photo_duplicates.py` (nouveau), `config.py`, `storage/migrations.py`
(migration 9), `storage/sqlite.py`, `pipeline.py`, `scrapers/enricher.py`, `notify/messages.py`,
`main.py`, `requirements.txt`, `tests/conftest.py`, `tests/test_photo_duplicates.py` (nouveau)

### Principe

La détection historique (prix ±5 € + 2 mots communs dans la localisation) échoue dès que les sites
décrivent l'adresse différemment (« Blagnac » sur Bien'ici, « Blagnac 31700 Centre » sur LBC). Les
photos, elles, sont presque toujours les mêmes, seulement redimensionnées et recompressées.

- **Empreinte** : dHash 64 bits de la 1ʳᵉ photo (image réduite à 9×8 en niveaux de gris, un bit par
  comparaison de pixels voisins), calculée avec **Pillow seul** — `imagehash` aurait ajouté numpy,
  scipy et PyWavelets pour le même résultat. Insensible à la taille, à la compression JPEG, à un
  léger flou (vérifié par les tests). Sans Pillow, l'étape est sautée avec un message.
- **Migration 9** : `photo_hash` (16 caractères hexa, indexé) et `photo_hash_attempts`.
- **Téléchargement** : `requests` (pas de navigateur), 150 photos au plus par run, 0,3 s entre deux,
  5 Mo maximum, `Content-Type` image exigé, des plus récentes aux plus anciennes. Un échec est
  retenté une fois au run suivant (`PHOTO_HASH_MAX_ATTEMPTS = 2`), puis abandonné.

### Rapprochement

Deux annonces sont le même bien si :

| Règle | Réglage |
|---|---|
| Sites différents | — |
| Empreintes à ≤ 6 bits d'écart sur 64 | `PHOTO_HASH_MAX_DISTANCE` |
| Prix à ±30 € (un site affiche HC, l'autre CC) | `PHOTO_DUP_PRICE_TOLERANCE` |
| Photo non générique : même empreinte sur > 3 annonces d'un même site = logo d'agence, ignorée ; image unie ignorée | `PHOTO_GENERIC_MAX_SAME_SITE` |

La plus récente est rattachée (`duplicate_of`) à la **racine** de la plus ancienne : jamais de chaîne
de doublons, jamais rattachée à une annonce du même site que sa racine. Les rattachements existants
ne sont pas modifiés.

### Intégration

- Fin de `scrape` (après la collecte, **avant l'analyse LLM** — un doublon réutilise l'analyse de
  l'original, donc un appel économisé — et avant les notifications) et fin de `enrich`.
- Notifications : une **nouvelle** annonce qui est un doublon n'est plus signalée (le bien est déjà
  connu) ; une baisse de prix sur un doublon l'est toujours. Vaut aussi pour les doublons texte.
- UI : rien de nouveau, le lien « aussi sur … » et le filtre « Doublons » existants s'appliquent.
- CLI : `python main.py dedupe [--limit N]` (rattrapage des annonces déjà en base).
- Tests : `PHOTO_DEDUP_ENABLED` est désactivé par défaut (`conftest`) — aucun téléchargement.

### Bilan

- Tests : `tests/test_photo_duplicates.py` (33 tests : robustesse de l'empreinte sur des photos
  synthétiques redimensionnées / recompressées / floutées, photos différentes, PNG, image illisible,
  image unie, lecture de `photos`, chaque règle de rapprochement, logo d'agence, racine sans chaîne,
  trois sites en une passe, téléchargement plafonné, échecs retentés puis abandonnés, limite par run,
  bout en bout LBC ↔ Bien'ici avec adresses différentes, notifications, CLI). Suite complète verte.
- ⚠️ **À valider en réel** : `python main.py dedupe`, puis dans l'UI filtrer un profil et vérifier
  2–3 liens « aussi sur … » créés par la photo (log `📷 Doublon par photo`). Si les CDN d'images
  répondent 403 (log en DEBUG), il faudra ajouter un en-tête `Referer` du site.
