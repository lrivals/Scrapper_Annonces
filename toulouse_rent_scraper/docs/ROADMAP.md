# Roadmap — Scrapper Annonces

> Document de suivi global des sprints. Mis à jour au fil de l'avancement.
>
> **Dernière mise à jour** : 2026-03-02

---

## Vue d'ensemble

```
Sprint 1 (Notifications & Export)   ✅
    ↓
Sprint 2 (Interface & Liens)         ✅
    ↓
Sprint 2-ter (Modernisation UI)      🔵 En cours
    ↓
Sprint 3 (Enrichissement)  ←→  Sprint 4 (PAP.fr)   [parallélisables]
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
| 3 | Enrichissement annonces | 🔲 À faire | 0/6 | — | — |
| 4 | Scraper PAP.fr | 🔲 À faire | 0/6 | — | — |
| 5 | Rapports Markdown avancés | 🔲 À faire | 0/6 | — | — |
| 2-bis | API REST & Dashboard | 🔲 À faire | 0/6 | — | — |

**Légende** : 🔲 À faire | 🔵 En cours | ✅ Terminé | ⏸️ En pause

---

## Sprint 1 — Notifications & Export

📄 Détail : [SPRINT_1.md](SPRINT_1.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 1.1 | Fix parsing prix SeLoger | ✅ | MIN_RENT_EUR=50, 24 annonces purgées |
| 1.2 | Export CSV/JSON | ✅ | `--export csv/json`, 10 tests |
| 1.3 | Notifications Telegram | ⏸️ | Reporté |
| 1.4 | Notification email SMTP | ⏸️ | Reporté |
| 1.5 | Purge annonces expirées | ✅ | `--purge`, colonne status, 6 tests |
| 1.6 | Tests notifications | ⏸️ | Dépend de 1.3/1.4 |

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

## Sprint 3 — Enrichissement des annonces

📄 Détail : [SPRINT_3.md](SPRINT_3.md)

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 3.1 | Schéma DB enrichi | 🔲 | |
| 3.2 | Extracteur détaillé SeLoger | 🔲 | |
| 3.3 | Extracteur détaillé LeBonCoin | 🔲 | |
| 3.4 | Pipeline d'enrichissement | 🔲 | |
| 3.5 | Rapports enrichis | 🔲 | |
| 3.6 | Tests enrichissement | 🔲 | |

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
| v0.6 | — | *Sprint 3+4 — Enrichissement + PAP.fr* |
| v0.7 | — | *Sprint 5 — Rapports avancés* |
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
| 2026-03-02 | Template HTML embarqué dans `ui.py` | Pas de dossier templates/, tout en un fichier |
| 2026-03-02 | Imports lazy dans `main.py` | `--ui` et `--check-links` sans playwright installé |
| 2026-03-02 | Playwright headless pour link check | Les SPAs (SeLoger, LBC) bloquent `requests.head()` — faux positifs garantis |
| 2026-03-02 | `--purge` déprécié pour SPAs | Marqué avec avertissement dans `cleaner.py`, remplacé par `--check-links` |

---

## Blocages & risques connus

| Risque | Impact | Mitigation |
|--------|--------|------------|
| DataDome (LBC) bloque l'IP | Haut | Profil Chrome persistant, délais longs, limite de runs |
| Changement de sélecteurs HTML | Moyen | Scripts de debug (`debug_card_html_*.py`), tests réguliers |
| Nominatim rate-limited (géocodage) | Faible | Cache local, coordonnées ENAC en dur |
| Trop de requêtes enrichissement | Moyen | `--limit` configurable, délais 5-10s |
| `--purge` (requests) sur SPAs | Haut | **Résolu** — utiliser `--check-links` à la place |

---

*Ce document est la source de vérité pour l'avancement du projet. Mettre à jour les statuts après chaque session de travail.*
