# Roadmap — Scrapper Annonces

> Document de suivi global des sprints. Mis à jour au fil de l'avancement.
>
> **Dernière mise à jour** : 2026-11-13 — Sprint 15 livré (15.3 SeLoger JSON, critères dans l’UI), Sprint 16 rédigé ; audit : [AUDIT_2026-11.md](AUDIT_2026-11.md)

---

## Vue d'ensemble

```
Sprint 1 (Notifications & Export)          ✅
    ↓
Sprint 2 (Interface & Liens)               ✅
    ↓
Sprint 2-ter (Modernisation UI)            ✅
    ↓
Sprint 6 (Qualité données)                 ✅
    ↓
Sprint 7 (Mode Document & Cache Géo)       ✅
    ↓
Sprint 8 (Actions UI directes)             ✅
    ↓
Sprint 3 (Enrichissement)  ←→  Sprint 4 (PAP.fr)   [parallélisables]
    ↓
Sprint 9 (Photos & Thumbnails)             ✅
    ↓
Sprint 10 (Vue Carte OpenStreetMap)        ✅
    ↓
Sprint 11 (Fiabilité des données)          ✅
    ↓
Sprint 14 (Profils multiples : ENAC + Blagnac) ✅
    ↓
Sprint 12 (Refactor & sécurité)            ✅
    ↓
Sprint 13 (Alerte & priorisation)          ✅
    ↓
Sprint 15 (Fiches détaillées & sources)    ✅
    ↓
Sprint 16 (Fiches complètes dès le scraping) 🔲
    ↓
Sprint 4 (PAP.fr)  — profite du refactor 12 et du modèle commun 15.7
    ↓
Sprint 5 (Rapports avancés)
    ↓
Sprint 2-bis (API REST & Dashboard)
```

---

## État des sprints

| Sprint | Titre | Statut | Progression | Début | Fin |
|--------|-------|--------|-------------|-------|-----|
| 1 | Notifications & Export | ✅ Terminé (partiel) | 3/6 livrées, 3 reportées | 2026-02-09 | 2026-02-09 |
| 2 | Interface & Vérification liens | ✅ Terminé | 4/4 | 2026-03-02 | 2026-03-02 |
| 2-ter | Modernisation UI (Design) | ✅ Terminé | 3/3 | 2026-03-02 | 2026-03-02 |
| 6 | Qualité données (Doublons & Expirés) | ✅ Terminé | 4/4 | 2026-03-06 | 2026-03-06 |
| 7 | Mode Document & Cache Géocodage | ✅ Terminé | 3/3 | 2026-03-21 | 2026-03-21 |
| 8 | Actions UI directes (scraping & clear BD) | ✅ Terminé | 3/3 | 2026-03-24 | 2026-03-24 |
| 3 | Enrichissement annonces | ✅ Terminé | 6/6 | 2026-03-25 | 2026-03-25 |
| 9 | Photos & Thumbnails | ✅ Terminé | 5/5 | 2026-03-25 | 2026-03-25 |
| 10 | Vue Carte OpenStreetMap | ✅ Terminé | 6/6 | 2026-03-25 | 2026-03-25 |
| 11 | Fiabilité des données (bugs audit) | ✅ Terminé | 7/7 (2 validations manuelles SeLoger) | 2026-11-03 | 2026-11-03 |
| 14 | Profils de recherche (ENAC + Blagnac) | ✅ Terminé | 8/8 (URL SeLoger Blagnac à capturer) | 2026-11-03 | 2026-11-03 |
| 12 | Refactor & sécurité | ✅ Terminé | 8/8 (compteurs à revalider au prochain scraping réel) | 2026-11-03 | 2026-11-03 |
| 13 | Alerte & priorisation | ✅ Terminé | 4/5 (13.5 reporté) | 2026-11-03 | 2026-11-03 |
| 15 | Fiches détaillées, tri affiné, nouvelles sources | 🔵 En cours | 4/8 (à valider sur les vrais sites / avec une clé d'API) | 2026-11-12 | — |
| 16 | Fiches complètes dès le scraping | 🔲 À faire | 0/6 | — | — |
| 4 | Scraper PAP.fr | 🔲 À faire | 0/6 | — | — |
| 5 | Rapports Markdown avancés | 🔲 À faire | 0/6 | — | — |
| 2-bis | API REST & Dashboard | 🔲 À faire | 0/6 | — | — |

**Légende** : 🔲 À faire | 🔵 En cours | ✅ Terminé | ⏸️ En pause

---

## Sprint 16 — Fiches complètes dès le scraping

📄 Détail : [SPRINT_16.md](SPRINT_16.md)

Une fois les liens récoltés, ouvrir les annonces retenues et extraire leur fiche **avant** score et notifications.

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 16.1 | Ouverture des fiches intégrée au pipeline | 🔲 | Par défaut ; `scrape --no-enrich` pour s'en passer |
| 16.2 | Sélection des annonces retenues | 🔲 | Annonces du run d'abord, par score ; doublons / exclues écartés |
| 16.3 | Budget par site et anti-ban | 🔲 | `DETAIL_VISITS_PER_RUN` ; un site bloqué n'arrête pas l'autre |
| 16.4 | Notifications avec la fiche complète | 🔲 | Surface, charges, DPE, distance exacte |
| 16.5 | UI, timer et résumé | 🔲 | systemd : `scrape --unattended` |
| 16.6 | Tests | 🔲 | |

---

## Sprint 15 — Fiches détaillées, tri affiné, nouvelles sources

📄 Détail : [SPRINT_15.md](SPRINT_15.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 15.1 | LBC : JSON `__NEXT_DATA__`, GPS exact, santé de l'extraction | ✅ | `main.py quality` ; valider les clés JSON sur une vraie page |
| 15.2 | LBC : annonces complètes dès la recherche | ✅ | Moins de visites de détail ; JSON périmé détecté |
| 15.3 | SeLoger : état JSON embarqué | ✅ | Recherche + détail ; URLs normalisées (migration 10) ; validé en réel |
| 15.4 | Analyse de la description par LLM | ✅ | LLM et clé de l’utilisateur (page « Connexion LLM ») ; une seule lecture par texte ; malus arnaque |
| 15.5 | Critères éliminatoires par profil | ✅ | Inconnu = conservé ; recalculé à chaque rescore ; saisie dans l’UI (page « Critères ») |
| 15.6 | Retours ⭐/👎 → poids appris | ✅ | Appliqués sur confirmation ; suivi des favoris |
| 15.7 | Source Bien'ici (API JSON) + modèle `Listing` | ✅ | `ApiScraper` : sources sans navigateur |
| 15.8 | Doublons par empreinte photo | ✅ | dHash Pillow ; `python main.py dedupe` |

---

## Sprint 11 — Fiabilité des données

📄 Détail : [SPRINT_11.md](SPRINT_11.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 11.1 | `parse_price` robuste | ✅ | `"1 200 €"` parsé 200 aujourd'hui |
| 11.2 | Réactivation dans `insert_annonce` | ✅ | `expired` → `active` si revue |
| 11.3 | Statut `hidden` au lieu du `DELETE` | ✅ | Les annonces supprimées reviennent |
| 11.4 | Géocodage fiable | ✅ | Suffixe conditionnel, cache négatif |
| 11.5 | URLs dérivées de la config | ✅ | LBC `price=350-max` incohérent |
| 11.6 | Doublons cohérents et persistés | ✅ | Colonne `duplicate_of` |
| 11.7 | Script de réparation des données | ✅ | `scripts/repair_data.py` |

---

## Sprint 14 — Profils de recherche multiples

📄 Détail : [SPRINT_14.md](SPRINT_14.md)

Nouveau cas d'usage : appartement ≈ 700 € (550–750 €, T1–T3) à ≤ 8 km du 14 Pl. Marcel Dassault, 31700 Blagnac.

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 14.1 | `SEARCH_PROFILES` dans la config | ✅ | `enac` + `blagnac` |
| 14.2 | URLs de recherche par profil | ✅ | URL SeLoger à capturer manuellement |
| 14.3 | Table `annonce_profiles` | ✅ | Migration des annonces existantes → `enac` |
| 14.4 | Filtre et pipeline par profil | ✅ | `match_profiles()`, une annonce ↔ N profils |
| 14.5 | CLI `--profile` | ✅ | |
| 14.6 | UI : sélecteur de profil | ✅ | Liste, carte centrée + rayon, export |
| 14.7 | Rapports & exports par profil | ✅ | |
| 14.8 | Tests | ✅ | |

---

## Sprint 12 — Refactor & sécurité

📄 Détail : [SPRINT_12.md](SPRINT_12.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 12.1 | `scrapers/browser.py` | ✅ | Session Chrome unique (remplace 3 copies) |
| 12.2 | `scrapers/antibot.py` | ✅ | Détection challenge unique |
| 12.3 | Découpage `BaseScraper.scrape()` | ✅ | ~210 lignes → orchestrateur |
| 12.4 | Migrations versionnées, index, historique prix | ✅ | `PRAGMA user_version`, `price_history` |
| 12.5 | Découpage UI | ✅ | `ui/` + templates Jinja |
| 12.6 | Sécurité UI | ✅ | CSRF, open redirect |
| 12.7 | CLI en sous-commandes | ✅ | `pipeline.py` |
| 12.8 | Hygiène du repo | ✅ | Config morte, deps, tests sans Playwright |

---

## Sprint 13 — Alerte & priorisation

📄 Détail : [SPRINT_13.md](SPRINT_13.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 13.1 | Notifications nouvelles annonces | ✅ | ntfy.sh / Telegram — remplace 1.3/1.4 |
| 13.2 | Planification systemd | ✅ | Timer user + verrou + alerte captcha |
| 13.3 | Score d'intérêt | ✅ | Prix CC, distance, €/m², meublé, DPE |
| 13.4 | Retry enrichissement | ✅ | Max 3 tentatives |
| 13.5 | Temps de trajet (stretch) | ⏸️ | OSRM vélo / Tisséo |

---

## Sprint 1 — Notifications & Export

📄 Détail : [SPRINT_1.md](SPRINT_1.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 1.1 | Fix parsing prix SeLoger | ✅ | MIN_RENT_EUR=50, 24 annonces purgées |
| 1.2 | Export CSV/JSON | ✅ | `--export csv/json`, 10 tests |
| 1.3 | Notifications Telegram | ✅ | Livré au Sprint 13.1 (ntfy + Telegram) |
| 1.4 | Notification email SMTP | ⏸️ | Reporté → remplacé par ntfy (13.1) |
| 1.5 | Purge annonces expirées | ✅ | `--purge`, colonne status, 6 tests |
| 1.6 | Tests notifications | ✅ | Livré au Sprint 13.1 (`tests/test_notify.py`) |

---

## Sprint 2 — Interface de navigation & Vérification des liens

📄 Détail : [SPRINT_2.md](SPRINT_2.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 2.1 | Interface Flask navigation | ✅ | `ui.py`, `--ui`, `--port`, filtres/tri |
| 2.2 | Suppression manuelle (UI) | ✅ | Bouton ✕ par ligne, flash message |
| 2.3 | Vérificateur liens Playwright | ✅ | `--check-links`, `--limit`, browser headless |
| 2.4 | Refactorisation imports lazy | ✅ | `--ui` et `--check-links` sans playwright |

---

## Sprint 2-ter — Modernisation UI (Design)

📄 Détail : [UI_MODERNIZATION.md](UI_MODERNIZATION.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 2.5 | Refonte CSS (Cards & Grid) | ✅ | Design tokens, layout responsif |
| 2.6 | Template UI "Premium" | ✅ | Intégration dans `ui.py` |
| 2.7 | Support photos & placeholders | ✅ | |

---

## Sprint 6 — Qualité des données (Doublons & Annonces supprimées)

📄 Détail : [SPRINT_6.md](SPRINT_6.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 6.1 | Mise à jour doublons au scraping | ✅ | `insert_annonce` retourne new/updated/unchanged |
| 6.2 | Détection doublons flous | ✅ | `find_potential_duplicates`, log warning |
| 6.3 | Patterns LBC manquants | ✅ | "le bien a déjà été vendu" + 5 autres patterns |
| 6.4 | Logs post-scraping enrichis | ✅ | Compteurs new/updated/unchanged/duplicates |

---

## Sprint 7 — Mode Document & Cache Géocodage

📄 Détail : [SPRINT_7.md](SPRINT_7.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 7.1 | Mode sélection UI | ✅ | Boutons + Doc, LocalStorage, badge compteur |
| 7.2 | Export Markdown (`/export-document`) | ✅ | Téléchargement `.md` avec annonces sélectionnées |
| 7.3 | Cache géocodage SQLite | ✅ | Table `geocoding_cache`, 0 appel redondant Nominatim |

---

## Sprint 8 — Actions UI directes

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 8.1 | Bouton "Vider la BD" avec confirmation | ✅ | Route `/clear-db`, `clear_db()` dans `sqlite.py` |
| 8.2 | Bouton "Lancer le scraping" | ✅ | Route `/start-scraping`, `subprocess.Popen` |
| 8.3 | Feedback statut scraping (polling JS) | ✅ | Route `/scraping-status`, spinner + reload auto |

---

## Sprint 3 — Enrichissement des annonces

📄 Détail : [SPRINT_3.md](SPRINT_3.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 3.1 | Schéma DB enrichi | ✅ | Colonnes enrichissement + migration auto |
| 3.2 | Extracteur détaillé SeLoger | ✅ | `scrapers/detail_extractors/seloger_detail.py` |
| 3.3 | Extracteur détaillé LeBonCoin | ✅ | `scrapers/detail_extractors/leboncoin_detail.py` |
| 3.4 | Pipeline d'enrichissement | ✅ | `scrapers/enricher.py`, `--enrich`, `--all --enrich` |
| 3.5 | Rapports enrichis | ✅ | `annonces_detaillees.md`, colonnes surface/DPE/pièces |
| 3.6 | Tests enrichissement | ✅ | `test_detail_extractors.py`, `test_enricher.py` |

---

## Sprint 9 — Photos & Thumbnails

📄 Détail : [SPRINT_9.md](SPRINT_9.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 9.1a | Extraction thumbnail — SeLoger | ✅ | `img[data-testid*="photo"]` + `img[src]` fallback |
| 9.1b | Extraction thumbnail — LeBonCoin | ✅ | `img[src*="leboncoin"]` + `img[data-src]` fallback |
| 9.2 | `photos` dans `insert_annonce` | ✅ | COALESCE — ne pas écraser les photos enrichies |
| 9.3 | Affichage photos dans l'UI | ✅ | `.card-image` 180px, `object-fit: cover`, `onerror` fallback |
| 9.4 | Documentation sprint | ✅ | `SPRINT_9.md`, `ROADMAP.md` mis à jour |

---

## Sprint 10 — Vue Carte OpenStreetMap

📄 Détail : [SPRINT_10.md](SPRINT_10.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 10.1 | Route `/api/map-data` | ✅ | JSON `{enac, listings[]}` avec coords via `geocoding_cache` |
| 10.2 | Intégration Leaflet.js | ✅ | CDN `leaflet@1.9.4`, tuiles OpenStreetMap, aucune clé API |
| 10.3 | Boutons toggle Liste / Carte | ✅ | Header UI, CSS `.btn-view`, état actif |
| 10.4 | Marqueur ENAC | ✅ | Point noir, popup « ENAC — 7 Av. Édouard Belin » |
| 10.5 | Marqueurs appartements | ✅ | Points verts, popup titre / prix / distance / lien |
| 10.6 | Gestion adresses non géocodées | ✅ | Compteur sous la carte, sans crash |
| C1 | Fix `invalidateSize()` Leaflet | ✅ | Carte grise au re-affichage corrigée (2026-03-26) |
| C2 | Persistance vue carte après filtrage | ✅ | `?view=map` dans l'URL + champ hidden dans le formulaire (2026-03-26) |
| C3 | Gestion erreur fetch `/api/map-data` | ✅ | `.catch()` avec message utilisateur (2026-03-26) |

---

## Sprint 4 — Scraper PAP.fr

📄 Détail : [SPRINT_4.md](SPRINT_4.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 4.1 | Analyse et reconnaissance PAP | 🔲 | |
| 4.2 | Configuration PAP | 🔲 | |
| 4.3 | Scraper PAP | 🔲 | |
| 4.4 | Extracteur détaillé PAP | 🔲 | Dépend Sprint 3 |
| 4.5 | Tests PAP | 🔲 | |
| 4.6 | Gestion multi-sites améliorée | 🔲 | |

---

## Sprint 5 — Rapports Markdown avancés

📄 Détail : [SPRINT_5.md](SPRINT_5.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 5.1 | Rapport enrichi détaillé | 🔲 | Dépend Sprint 3 |
| 5.2 | Système de scoring | 🔲 | |
| 5.3 | Rapport comparatif (diff) | 🔲 | |
| 5.4 | Rapport par quartier | 🔲 | |
| 5.5 | Export PDF | 🔲 | |
| 5.6 | Rapport Top 10 | 🔲 | |

---

## Sprint 2-bis — API REST & Dashboard

Tâches originellement prévues en Sprint 2, reportées.

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 2-bis.1 | API REST FastAPI | 🔲 | |
| 2-bis.2 | Dashboard Streamlit + carte Folium | 🔲 | Remplace l'UI Flask actuelle |
| 2-bis.3 | Configuration dynamique | 🔲 | Table `config` en DB |
| 2-bis.4 | Historique & tendances | 🔲 | Table `stats_history` |
| 2-bis.5 | Dockerisation | 🔲 | |
| 2-bis.6 | Tests API | 🔲 | Dépend 2-bis.1 |

---

## Historique des releases

| Version | Date | Contenu |
|---------|------|---------|
| v0.1 | 2026-02-06 | MVP — Scraper SeLoger + filtres + SQLite |
| v0.2 | 2026-02-08 | Ajout scraper LeBonCoin |
| v0.3 | 2026-02-09 | Module reporting Markdown + colonne `created_at` + fix tests LBC |
| v0.4 | 2026-02-09 | Sprint 1 partiel — Fix prix, export CSV/JSON, purge expirées |
| v0.5 | 2026-03-02 | Sprint 2 — Interface Flask, suppression UI, vérif. liens Playwright |
| v0.5.1 | 2026-03-06 | Sprint 6 — Gestion doublons, patterns LBC expirés, logs enrichis |
| v0.5.2 | 2026-03-21 | Sprint 7 — Mode document UI, export Markdown, cache géocodage SQLite |
| v0.5.3 | 2026-03-24 | Sprint 8 — Boutons UI "Vider la BD" et "Lancer le scraping" en arrière-plan |
| v0.6 | 2026-03-25 | Sprint 3 — Enrichissement (extracteurs détaillés, pipeline, rapports, tests) |
| v0.7 | 2026-03-25 | Sprint 9 — Photos & Thumbnails dans les cartes UI |
| v0.8 | 2026-03-25 | Sprint 10 — Vue Carte OpenStreetMap (Leaflet.js, toggle Liste/Carte, marqueurs ENAC + appartements) |
| v0.8.1 | 2026-03-26 | Sprint 10 corrections — invalidateSize Leaflet, persistance vue carte, gestion erreur fetch |
| v0.9 | — | *Sprint 4+5 — PAP.fr + Rapports avancés* |
| v1.0 | — | *Sprint 2-bis — API REST + Dashboard + Docker* |

---

## Décisions techniques

| Date | Décision | Contexte |
|------|----------|----------|
| 2026-02-06 | SQLite comme DB | Léger, embarqué, suffisant pour usage personnel |
| 2026-02-06 | Playwright + Chrome CDP | Contourner les protections anti-bot (DataDome) |
| 2026-02-08 | `data-test-id` pour LBC | Migration depuis `data-qa-id`, plus stable |
| 2026-02-09 | `created_at` via migration auto | Compatibilité avec DB existantes sans perte de données |
| 2026-02-09 | PAP.fr comme 3ème source | 100% particuliers, pas de frais d'agence, bon volume Toulouse |
| 2026-02-09 | Colonne `status` (active/expired) | Migration auto, purge via HEAD request |
| 2026-02-09 | MIN_RENT_EUR = 50 | Filtrer garages et prix aberrants (11-21€) |
| 2026-03-02 | Flask plutôt que FastAPI+Streamlit | Périmètre "petite interface" — 1 fichier, 0 dépendance lourde |
| 2026-03-02 | Template HTML embarqué dans `ui.py` | Pas de dossier templates/, tout en un fichier — **remplacé le 2026-11-03** par le package `ui/` (Sprint 12) |
| 2026-03-02 | Imports lazy dans `main.py` | `--ui` et `--check-links` sans playwright installé |
| 2026-03-02 | Playwright headless pour link check | Les SPAs (SeLoger, LBC) bloquent `requests.head()` — faux positifs garantis |
| 2026-03-02 | `--purge` déprécié pour SPAs | Marqué avec avertissement dans `cleaner.py`, remplacé par `--check-links` |
| 2026-03-06 | `insert_annonce` retourne new/updated/unchanged | Meilleure traçabilité des runs, mise à jour `scraped_at` et `price` |
| 2026-03-06 | Détection doublons flous | Comparaison prix ±5€ + mots-clés `location_raw` — log warning uniquement |
| 2026-03-21 | Cache géocodage SQLite | Table `geocoding_cache` — évite les appels redondants Nominatim, respect ToS 1 req/s |
| 2026-03-21 | Mode Document via LocalStorage | Sélection persistante entre pages, pas de state serveur — cohérent avec l'architecture 1-fichier |
| 2026-03-24 | `subprocess.Popen` pour le scraping en arrière-plan | Isole le processus scraping du serveur Flask, évite le blocage de l'UI — polling JS côté client (setInterval 3s) sans WebSockets |
| 2026-03-25 | Thumbnail via CDN direct (pas de proxy) | Les CDNs SeLoger/LBC sont accessibles directement — `referrerpolicy="no-referrer"` + `onerror` fallback pour les cas bloqués |
| 2026-03-25 | `COALESCE(photos, ?)` dans `insert_annonce` | Empêche d'écraser les photos complètes (enrichissement Sprint 3) lors d'un re-scraping de la liste |
| 2026-03-25 | Leaflet.js via CDN pour la carte | Aucune clé API, tuiles OSM gratuites, aucune dépendance Python supplémentaire — `L.divIcon` pour les marqueurs personnalisés |
| 2026-03-25 | LEFT JOIN `geocoding_cache` pour les coords carte | Réutilise le cache existant sans nouvelle colonne en base — les annonces sans entrée cache sont comptabilisées mais non affichées |
| 2026-11-03 | Score stocké par profil, avec un loyer cible par profil | Loyer et distance dépendent du profil ; le minimum de budget (50 €) n'est pas un loyer idéal |
| 2026-11-03 | ntfy.sh en publication JSON, `.env` lu sans dépendance | Titres avec « — » et « € » impossibles en en-têtes HTTP (latin-1) |
| 2026-11-03 | Timer systemd 3×/jour ± 20 min, verrou fcntl, pause de 6 h après un blocage | Comportement moins « robot » ; pas de double run timer + UI ; limite le risque de ban IP |
| 2026-11-03 | Package `ui/` (templates Jinja + statiques) | `ui.py` dépassait 1400 lignes ; le SQL passe dans `storage/queries.py` |
| 2026-11-03 | Migrations versionnées (`PRAGMA user_version`) + WAL | Schéma rejoué une seule fois ; l'UI peut lire pendant un scraping |
| 2026-11-03 | Jeton CSRF de session sur l'UI | Une page web quelconque pouvait vider la base via `localhost:5000/clear-db` |
| 2026-11-03 | CLI en sous-commandes, ancienne syntaxe traduite | Clarté (`scrape`, `enrich`, `ui`…) sans casser les habitudes |
| 2026-11-03 | Masquage global plutôt que par profil | Budgets ENAC (≤ 500 €) et Blagnac (≥ 550 €) disjoints — une annonce ne matche jamais les deux |
| 2026-11-03 | Profils de recherche (Sprint 14) juste après le Sprint 11 | Nouveau besoin Blagnac ≈ 700 € ; table `annonce_profiles` plutôt qu'une colonne `profile` car une annonce peut matcher plusieurs cibles |
| 2026-11-13 | Ouverture des fiches dans le pipeline, avant score et notifications (Sprint 16) | `scrape --enrich` enrichissait après les notifications : alertes sans surface/DPE, critères éliminatoires de la fiche ignorés, post-traitement fait deux fois |
| 2026-11-03 | Sprints 11→13 avant PAP.fr | Audit : bugs de données (prix, statuts, géocodage) et code Chrome dupliqué à corriger avant d'ajouter une 3ᵉ source — voir [AUDIT_2026-11.md](AUDIT_2026-11.md) |

---

## Blocages & risques connus

| Risque | Impact | Mitigation |
|--------|--------|------------|
| DataDome (LBC) bloque l'IP | Haut | Profil Chrome persistant, délais longs, limite de runs |
| Changement de sélecteurs HTML | Moyen | Scripts de debug (`scripts/debug/capture_cards_*.py`), tests réguliers |
| Nominatim rate-limited (géocodage) | Faible | Cache local, coordonnées ENAC en dur |
| Trop de requêtes enrichissement | Moyen | `--limit` configurable, délais 5-10s |
| `--purge` (requests) sur SPAs | Haut | **Résolu** — utiliser `--check-links` à la place |

---

*Ce document est la source de vérité pour l'avancement du projet. Mettre à jour les statuts après chaque session de travail.*
