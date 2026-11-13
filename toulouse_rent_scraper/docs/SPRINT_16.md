# Sprint 16 — Fiches complètes dès le scraping

> **Date** : 2026-11-13
> **Statut** : 🔲 À faire
> **Origine** : question « le scraping ouvre-t-il les annonces une à une ? Peut-on le faire sur les liens récoltés ? »
> **Prérequis** : [Sprint 15](SPRINT_15.md) (extracteurs JSON 15.1/15.2, critères 15.5, dedup photo 15.8), [Sprint 13](SPRINT_13.md) (score, notifications), [Sprint 12](SPRINT_12.md) (`chrome_session`, verrou, anti-ban)

## Objectif

Une fois les liens récoltés sur les pages de recherche, **ouvrir automatiquement les
annonces retenues** (celles qui passent le filtre d'au moins un profil) et en extraire tout
ce que la page de détail contient (surface, pièces, charges, DPE/GES, description,
photos, GPS exact…), **avant** de calculer les scores et d'envoyer les notifications.

## Constat de départ

Aujourd'hui, deux étapes distinctes :

| Étape | Ce qu'elle fait | Déclenchement |
|---|---|---|
| `scrape` (`pipeline.run_scraping`) | Lit les **cartes** des pages de recherche (+ JSON de recherche LBC, 15.2). N'ouvre aucune annonce. | Bouton UI, timer, CLI |
| `enrich` (`scrapers/enricher.enrich_annonces`) | Ouvre les annonces **une à une** et lance l'extracteur du site | `main.py enrich`, ou `scrape --enrich` (timer : `--limit 20`) |

L'ouverture une à une existe donc déjà, et elle tourne déjà sur les liens stockés en base.
Mais :

1. **Optionnelle** : le bouton « Lancer le scraping » de l'UI (`ui/routes.py`, `start_scraping`)
   lance `main.py scrape` sans `--enrich` → les fiches restent incomplètes.
2. **Trop tard** : avec `scrape --enrich`, l'enrichissement tourne **après** `run_scraping`.
   Dedup photo, analyse LLM, rescore et **notifications** sont déjà passés :
   - l'alerte d'une nouvelle annonce part sans surface, DPE ni position exacte ;
   - une annonce éliminée par un critère qui n'apparaît que sur la fiche (DPE G, surface
     trop petite… 15.5) peut quand même être notifiée ;
   - dedup photo, LLM et rescore sont relancés une 2ᵉ fois à la fin de l'enrichissement.
3. **Mauvaise cible** : `get_pending_annonces` (`storage/sqlite.py`) prend tout le stock
   `pending` trié par date. Il ne vise pas en priorité les annonces du run, n'écarte ni
   les doublons (`duplicate_of`), ni les annonces déjà exclues par tous les profils
   (`annonce_profiles.excluded_reasons`), et ignore le score.
4. **Tout ou rien** : un challenge anti-bot non résolu fait `break` sur tout
   l'enrichissement, même pour l'autre site.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 16.1 | Ouverture des fiches intégrée au pipeline | 🔲 | Avant dedup photo / LLM / rescore / notifications ; activée par défaut |
| 16.2 | Sélection des annonces retenues | 🔲 | Annonces du run d'abord, par score ; doublons et exclues écartés |
| 16.3 | Budget par site et anti-ban | 🔲 | Plafond de visites par site ; un site bloqué n'arrête pas l'autre |
| 16.4 | Notifications avec la fiche complète | 🔲 | Surface, charges, DPE, distance exacte dans l'alerte |
| 16.5 | UI, timer et résumé | 🔲 | Bouton UI et systemd suivent le défaut ; avancement visible |
| 16.6 | Tests | 🔲 | Ordre du pipeline, sélection, budget, CLI |

Hors périmètre :
- **15.3 SeLoger JSON embarqué** : reste au Sprint 15 ; une fois fait, une partie des
  visites SeLoger deviendra inutile (même mécanisme que `LBC_SEARCH_JSON_SKIPS_DETAIL`).
- **Bien'ici** : l'API donne déjà l'annonce entière (`Listing.authoritative` → `done`),
  aucune visite nécessaire.
- **Visites en parallèle** : refusé, trop visible pour DataDome.

---

## 16.1 — Ouverture des fiches intégrée au pipeline

**Fichiers** : `scrapers/enricher.py`, `pipeline.py`, `main.py`

### Nouvel ordre de `run_scraping`

```
recherches (profil × site)  → process_annonces (filtre, insertion, profils)
        ↓
rescore() léger             → score provisoire pour classer les fiches à ouvrir (16.2)
        ↓
OUVERTURE DES FICHES        → open_annonces(...)   ← nouveau
        ↓
santé de l'extraction → dedup photo (15.8) → analyse LLM (15.4) → rescore → notifications → rapports
```

### Découpage de l'enricher

- Extraire de `enrich_annonces` un noyau
  `open_annonces(annonces, unattended=False, budget=None) -> EnrichStats` : la boucle de
  visite actuelle (navigation, challenge, annonce retirée, `_extractor_for`,
  `update_annonce_enrichment`, `_refresh_distances`), **sans** post-traitement.
- `enrich_annonces` (commande `enrich`, inchangée pour l'utilisateur) devient :
  `get_pending_annonces` → `open_annonces` → post-traitement actuel (santé, favoris
  retirés, dedup photo, LLM, rescore).
- `run_scraping` appelle `open_annonces` puis fait **une seule fois** le post-traitement
  (il le fait déjà), en fusionnant les lignes de santé de la recherche et celles des fiches.
- Les favoris retirés détectés pendant l'ouverture (`gone`) sont notifiés comme aujourd'hui
  (`storage.cleaner._notify_gone`).

### CLI

- `scrape` ouvre les fiches **par défaut**.
- `scrape --no-enrich` : comportement actuel (recherche seule).
- `scrape --enrich` : accepté, sans effet (compatibilité timer / habitudes), avec un
  `logger.debug`.
- `--limit` reste le plafond **global** de visites du run.
- `cmd_scrape` n'appelle plus `cmd_enrich` après `run_scraping`.

**Critères d'acceptation**
- Un `scrape` sans option ouvre les annonces retenues du run avant l'envoi des notifications.
- Dedup photo, LLM et rescore ne tournent qu'une fois par run.
- `main.py enrich` garde exactement son comportement actuel.

---

## 16.2 — Sélection des annonces retenues

**Fichiers** : `pipeline.py` (`RunStats`, `process_annonces`), `storage/sqlite.py`

- `RunStats.retained_urls: List[str]` : URL de chaque annonce conservée par
  `process_annonces` (≥ 1 profil), quel que soit le résultat d'insertion
  (new, reactivated, updated, unchanged). Une `unchanged` déjà `done` sera écartée par la requête.
- Nouvelle requête `get_annonces_to_open(urls, limit)` :
  - `COALESCE(status, 'active') = 'active'` ;
  - `duplicate_of IS NULL` (on ouvre l'original, pas le doublon) ;
  - `enrichment_status = 'pending'`, ou `error` rejouable (mêmes règles que
    `get_pending_annonces` : `ENRICHMENT_MAX_ATTEMPTS`, `ENRICHMENT_RETRY_DELAY_HOURS`) ;
  - site ayant un extracteur (`SeLoger`, `LeBonCoin`) : jamais de `site inconnu` ;
  - **pas exclue par tous ses profils** : au moins une ligne `annonce_profiles` avec
    `excluded_reasons IS NULL`, ou favori ⭐ (cohérent avec `annonces_for_notification`).
    Un critère « inconnu » ne fait pas exclure (15.5) : une annonce sans DPE est ouverte.
- Ordre :
  1. annonces du run (`url IN (…)`), par **meilleur score de profil** décroissant ;
  2. puis rattrapage du stock `pending` plus ancien, par score puis `created_at DESC`,
     dans la limite du budget restant.
- `get_pending_annonces` reste pour la commande `enrich`.

**Critères d'acceptation**
- Un doublon, une annonce masquée/expirée ou exclue par tous les profils n'est jamais ouverte.
- À budget limité, les meilleures annonces du run passent en premier.

---

## 16.3 — Budget par site et anti-ban

**Fichiers** : `config.py`, `scrapers/enricher.py`

```python
# Sprint 16 — visites de pages de détail par run de scraping (le reste attend le run suivant)
DETAIL_VISITS_PER_RUN = {"LeBonCoin": 15, "SeLoger": 15}
```

- Visites **groupées par site** ; pause `PROFILE_SWITCH_MIN/MAX_DELAY` entre deux sites,
  `ENRICHMENT_MIN/MAX_DELAY` entre deux fiches (inchangé).
- Mode `unattended` : site sauté si `antibot.recently_blocked(site)` (même règle que la
  recherche).
- Challenge non résolu (`wait_for_challenge` → False) : `record_block(site)` puis
  **arrêt de ce site seulement** ; les fiches de l'autre site sont quand même ouvertes.
- Si la recherche d'un site a déjà été bloquée pendant ce run, on n'ouvre pas ses fiches.
- Une seule `chrome_session` pour toute la phase (le verrou fcntl couvre déjà tout `scrape`).

**Critères d'acceptation**
- Jamais plus de `DETAIL_VISITS_PER_RUN[site]` fiches ouvertes par site et par run.
- Un captcha LBC non résolu n'empêche pas l'ouverture des fiches SeLoger.

---

## 16.4 — Notifications avec la fiche complète

**Fichiers** : `notify/messages.py` (`_line`, `build_messages`), `storage/sqlite.py`
(`annonces_for_notification`)

Le filtrage existe déjà (score ≥ `NOTIFY_MIN_SCORE`, `excluded_reasons IS NULL`,
doublons écartés). Il devient juste car il s'applique maintenant **après** l'ouverture.

- `annonces_for_notification` renvoie en plus `surface_m2`, `nb_rooms`, `charges`,
  `dpe_rating`, `geo_precision`.
- `_line` : `T2 · 38 m² · 690 € (+40 € ch.) · DPE C · 5,2 km` ; « ≈ » devant la
  distance si `geo_precision != 'exact'` ; champs absents simplement omis.

**Critères d'acceptation**
- Une annonce exclue par un critère révélé par sa fiche (ex. DPE G) n'est pas notifiée.
- Le message d'une annonce enrichie affiche surface, charges et DPE.

---

## 16.5 — UI, timer et résumé

**Fichiers** : `ui/routes.py`, `deploy/scraper.service`, `pipeline.py`, `scrapers/enricher.py`

- UI : rien à passer, le défaut CLI suffit. Logs lisibles par la ligne d'avancement
  existante (`_last_log_line`) : `Ouverture des fiches 4/18 (LeBonCoin)`.
- `deploy/scraper.service` : `main.py scrape --unattended` (le budget vient de la config ;
  `--enrich --limit 20` retirés).
- `RunStats` : `opened`, `enriched`, `expired`, `relocated`, ajoutés à `log_summary`
  (« Fiches ouvertes : 18 — enrichies 16, retirées 1, repositionnées GPS 12 »).
- Mettre à jour le README (commandes) et la section « Décisions techniques » de la roadmap.

---

## 16.6 — Tests

| Fichier | Cas |
|---|---|
| `tests/test_pipeline.py` | ordre recherche → ouverture → rescore → notify (enricher factice qui enregistre l'appel) ; `--no-enrich` n'ouvre rien ; annonce exclue après sa fiche → pas d'événement notifié |
| `tests/test_storage.py` | `get_annonces_to_open` : doublon, masquée, exclue par tous les profils, favori exclu mais ouvert, Bien'ici écarté, `error` rejouable, ordre run/score/stock |
| `tests/test_enricher.py` | budget par site respecté ; challenge non résolu sur LBC → SeLoger continue ; `enrich_annonces` inchangé (post-traitement toujours fait) |
| `tests/test_cli.py` | `scrape` ouvre par défaut, `--no-enrich`, `--enrich` toléré |
| `tests/test_notify.py` | `_line` avec / sans surface, charges, DPE, distance approx |

---

## Risques

| Risque | Mitigation |
|---|---|
| Run plus long (5–10 s par fiche → ~3–5 min pour 30 fiches) | Budget par site ; acceptable pour 3 runs/jour |
| DataDome LBC : plus de pages vues par run | Budget prudent (15), réglable ; arrêt du site au 1ᵉʳ challenge ; `BLOCK_COOLDOWN_HOURS` respecté |
| Stock `pending` important au premier run | Rattrapage progressif, plafonné par le budget |
| Changement de mise en page d'une fiche | Alerte de santé existante (15.1), `python main.py quality` |

## Vérification de fin de sprint

1. `pytest` vert.
2. `python main.py scrape --profile enac --site leboncoin` réel : logs « Ouverture des
   fiches », fiches `done` en base, notification reçue avec surface / DPE.
3. `python main.py scrape --no-enrich` : aucune fiche ouverte.
4. Bouton UI : avancement visible pendant l'ouverture.
