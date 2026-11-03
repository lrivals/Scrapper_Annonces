# Sprint 13 — Alerte & priorisation

> **Date** : —
> **Statut** : 🔲 À faire
> **Origine** : [AUDIT_2026-11.md](AUDIT_2026-11.md) — F1 à F4 ; reprend les tâches 1.3/1.4/1.6 reportées du [Sprint 1](SPRINT_1.md)
> **Prérequis** : [Sprint 12](SPRINT_12.md) (`chrome_session`, `antibot.wait_for_challenge(on_challenge=…)`, `pipeline.process_annonces`, migrations versionnées)

## Objectif

Être prévenu **vite** des bonnes annonces et savoir lesquelles traiter en premier :
scraping planifié, notification des nouveautés, score d'intérêt, enrichissement
qui se rattrape tout seul.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 13.1 | Notifications nouvelles annonces | 🔲 | ntfy.sh (défaut) ou Telegram |
| 13.2 | Planification systemd | 🔲 | Timer user, `SCRAPE_FREQUENCY_HOURS` |
| 13.3 | Score d'intérêt | 🔲 | `scoring.py` + tri UI |
| 13.4 | Retry de l'enrichissement | 🔲 | `enrichment_attempts`, max 3 |
| 13.5 | Temps de trajet (stretch) | 🔲 | OSRM vélo / Tisséo |

---

## 13.1 — Notifications nouvelles annonces

**Fichiers** : `notify/__init__.py`, `notify/ntfy.py`, `notify/telegram.py` (nouveaux), `pipeline.py`, `config.py`, `.env.example`

- Interface : `send(title: str, body: str, url: str | None = None, priority: str = "default") -> bool`.
- **ntfy.sh** (recommandé : aucun compte, appli mobile, un `POST` HTTP) :
  ```python
  requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=body.encode(),
                headers={"Title": title, "Click": url, "Priority": priority, "Tags": "house"})
  ```
  Topic long et aléatoire (le topic fait office de secret).
- **Telegram** (optionnel) : `sendMessage` avec `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
- Secrets dans `.env` (déjà ignoré par git), chargés via `python-dotenv` ; `NOTIFY_BACKEND = "ntfy" | "telegram" | None`.
- **Déclenchement** : dans `pipeline.process_annonces`, collecter les annonces `new` (et `updated` si baisse de prix ≥ `NOTIFY_PRICE_DROP_EUR`) ; un message groupé par run si > 3 nouveautés, sinon un message par annonce (titre, prix, distance, score, lien).
- **Seuil** : ne notifier que si `score >= NOTIFY_MIN_SCORE` (13.3) — évite le bruit.
- Échec d'envoi : loggé, jamais bloquant pour le pipeline.
- Commande `python main.py notify-test`.

**Tests** : `requests.post` mocké ; regroupement ; seuil ; backend `None` = no-op.

## 13.2 — Planification systemd

**Fichiers** : `deploy/scraper.service`, `deploy/scraper.timer`, `docs/` (section README)

```ini
# ~/.config/systemd/user/scraper.timer
[Timer]
OnCalendar=*-*-* 08,13,19:00
RandomizedDelaySec=20min
Persistent=true
```

- Service `Type=oneshot`, `ExecStart=<venv>/bin/python main.py scrape --enrich`, `Environment=DISPLAY=:0` (Chrome non headless, DataDome).
- Horaires fixes + délai aléatoire plutôt qu'un intervalle strict : comportement plus humain ; `SCRAPE_FREQUENCY_HOURS` remplacé par `SCRAPE_SCHEDULE` documenté.
- **Challenge en mode planifié** : `wait_for_challenge(on_challenge=lambda: notify.send("Captcha à résoudre", priority="high"))`, timeout porté à 10 min ; si non résolu, on abandonne le site **sans** retenter (évite le blocage IP).
- **Verrou** : fichier `data/.scrape.lock` (`fcntl.flock`) pour empêcher deux runs simultanés (timer + bouton UI).
- Garde-fou anti-ban : si un blocage a eu lieu dans les 6 dernières heures (horodatage dans `data/.last_block`), sauter LBC.

## 13.3 — Score d'intérêt

**Fichiers** : `scoring.py` (nouveau), migration `score REAL`, `ui/`

Score 0–100, pondérations dans `config.py` (`SCORE_WEIGHTS`) :

| Critère | Calcul | Poids défaut |
|---|---|---|
| Loyer charges comprises | `price + (charges or 0)`, linéaire entre `MAX_RENT_EUR` (0) et `MIN_TARGET` (1) | 35 |
| Distance ENAC | linéaire 0 km (1) → `MAX_DISTANCE_KM` (0) ; remplacé par temps de trajet si 13.5 | 30 |
| €/m² | relatif à la médiane des annonces actives | 15 |
| Meublé | 1 si `furnished`, 0.5 si inconnu | 10 |
| DPE | A–C = 1, D = 0.6, E = 0.3, F–G = 0 (passoire), inconnu = 0.5 | 10 |

- Critère manquant ⇒ valeur neutre, jamais d'exclusion.
- Recalcul : après insertion, après enrichissement, et `python main.py rescore`.
- UI : tri « Score » par défaut, pastille colorée, détail au survol ; carte : couleur des marqueurs selon score.
- Export Markdown candidature : ajouter le score.

**Tests** : fonctions pures par critère + score global sur annonces types.

## 13.4 — Retry de l'enrichissement

**Fichiers** : `storage/` (migration `enrichment_attempts INTEGER DEFAULT 0`), `scrapers/enricher.py`

- `get_pending_annonces` sélectionne `pending` **ou** (`error` et `enrichment_attempts < 3` et `enriched_at` > 24 h).
- Incrémenter `enrichment_attempts` à chaque tentative ; après 3 échecs → `failed` (visible dans l'UI).
- Si la page renvoie « annonce supprimée » → `status='expired'` directement (réutiliser les patterns de `storage/cleaner.py`).
- Enregistrer `error_detail` (actuellement produit par l'enricher mais filtré par `allowed_fields`).

## 13.5 — Temps de trajet (stretch)

- Vélo / à pied : API OSRM publique (`router.project-osrm.org`, profil `bike`) — gratuite, pas de clé ; cache en table `travel_cache(lat, lon, mode, minutes)`.
- Transports en commun : API Tisséo (clé gratuite sur demande) ou approximation « distance à la station métro B la plus proche » (liste statique des stations Ramonville → Saint-Agne dans `config.py`) — à évaluer.
- Colonne `travel_min_bike`, affichée dans l'UI et utilisée par le score (13.3).

---

## Critères d'acceptation

- [ ] Une nouvelle annonce au-dessus du seuil génère une notification sur le téléphone en < 1 min après la fin du run.
- [ ] Le timer systemd lance 3 runs/jour sans intervention ; un captcha déclenche une notification.
- [ ] Deux runs simultanés sont impossibles.
- [ ] L'UI trie par score par défaut ; le score est explicable (détail par critère).
- [ ] Une annonce en `error` est retentée au plus 3 fois.
