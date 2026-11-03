# Sprint 13 — Alerte & priorisation

> **Date** : 2026-11-03
> **Statut** : ✅ Terminé (13.1 → 13.4) — 13.5 reporté ; activation des notifications et du timer à faire de ton côté (voir bilan)
> **Origine** : [AUDIT_2026-11.md](AUDIT_2026-11.md) — F1 à F4 ; reprend les tâches 1.3/1.4/1.6 reportées du [Sprint 1](SPRINT_1.md)
> **Prérequis** : [Sprint 12](SPRINT_12.md) (`chrome_session`, `antibot.wait_for_challenge(on_challenge=…)`, `pipeline.process_annonces`, migrations versionnées)

## Objectif

Être prévenu **vite** des bonnes annonces et savoir lesquelles traiter en premier :
scraping planifié, notification des nouveautés, score d'intérêt, enrichissement
qui se rattrape tout seul.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 13.1 | Notifications nouvelles annonces | ✅ | ntfy.sh (défaut) ou Telegram |
| 13.2 | Planification systemd | ✅ | Timer user, `SCRAPE_FREQUENCY_HOURS` |
| 13.3 | Score d'intérêt | ✅ | `scoring.py` + tri UI |
| 13.4 | Retry de l'enrichissement | ✅ | `enrichment_attempts`, max 3 |
| 13.5 | Temps de trajet (stretch) | ⏸️ | OSRM vélo / Tisséo |

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

- [ ] Une nouvelle annonce au-dessus du seuil génère une notification sur le téléphone en < 1 min après la fin du run — **code et tests en place** (envoi en fin de run, après le calcul des scores) ; à valider après avoir rempli `.env` (`python main.py notify-test`).
- [ ] Le timer systemd lance 3 runs/jour sans intervention ; un captcha déclenche une notification — **unités écrites et validées par `systemd-analyze verify`**, notification de captcha testée ; activation (`systemctl --user enable --now scraper.timer`) laissée à ton choix.
- [x] Deux runs simultanés sont impossibles : verrou `fcntl` testé avec un second processus ; l'UI suit un run lancé par le timer au lieu d'en démarrer un autre.
- [x] L'UI trie par score par défaut ; le score est explicable (détail par critère au survol, couleur des marqueurs de la carte).
- [x] Une annonce en `error` est retentée au plus 3 fois, puis passe en `failed` (« détails indisponibles » dans l'UI).

## Bilan d'implémentation (2026-11-03)

Tests : **261 passés, 1 ignoré** (195 avant le sprint), résultat identique sans Playwright. Nouveaux fichiers de test : `test_scoring.py`, `test_notify.py`, `test_scheduling.py` ; `test_enricher.py`, `test_pipeline.py` et `test_ui.py` sont étendus. Une fixture automatique redirige le verrou et la mémoire des blocages vers un dossier temporaire, et coupe les notifications : aucun test n'écrit dans `data/` ni n'appelle un service.

### 13.3 — Score
- `scoring.py` : 5 critères en fonctions pures, score sur 100 et détail par critère. Un critère inconnu vaut 0.5.
- **Écart** : le score est stocké **par profil** (`annonce_profiles.score`, `score_detail`) et non sur `annonces`, car loyer et distance dépendent du profil.
- **Écart** : ajout de `target_rent_eur` par profil (ENAC 350 €, Blagnac 600 €). Le « MIN_TARGET » prévu n'existait pas, et `min_rent_eur` (50 € pour ENAC) donnait 0,11 à un studio à 450 €.
- Recalcul après chaque scraping et chaque enrichissement, et via `python main.py rescore`.
- Base locale : 82 annonces notées (min 23, médiane 39, max 76), dont 6 au-dessus du seuil de notification. Aucune n'est encore enrichie : €/m², meublé et DPE sont neutres pour l'instant.

### 13.4 — Retry de l'enrichissement
- Migration 3 : `enrichment_attempts`, `error_detail`. Les erreurs existantes comptent comme une tentative.
- `get_pending_annonces` : les `pending` d'abord, puis les `error` à moins de 3 tentatives et dont le dernier essai date de plus de 24 h. Le seuil est calculé en Python : `enriched_at` est au format ISO, que la comparaison avec `datetime('now')` de SQLite fausserait.
- Une page « annonce supprimée » passe l'annonce en `expired` sans extraction (`storage.cleaner.is_expired_content`).

### 13.1 — Notifications
- Package `notify/` : `send()` (ntfy ou Telegram, ne lève jamais d'exception), `notify_events()`, `notify_captcha()`, et `messages.py` qui filtre par score et regroupe par profil.
- **Écart** : ntfy est appelé en **publication JSON**, pas avec les en-têtes HTTP prévus. Les en-têtes n'acceptent que du latin-1, donc « — » et « € » dans les titres auraient fait échouer l'envoi.
- **Écart** : les secrets sont lus par un petit chargeur `.env` dans `config.py`, plutôt qu'avec `python-dotenv` (une dépendance de moins). L'environnement réel reste prioritaire. Modèle : `.env.example`.
- Événements : nouvelle annonce **pour un profil**, et baisse de loyer ≥ `NOTIFY_PRICE_DROP_EUR` (20 €). Seuil `NOTIFY_MIN_SCORE` = 55 ; un seul récapitulatif au-delà de 3 annonces par profil.
- `python main.py notify-test`.

### 13.2 — Planification
- `deploy/scraper.service` + `scraper.timer` : 8h, 13h et 19h, ± 20 min, avec `Persistent=true`. Commande lancée : `scrape --enrich --limit 20 --unattended`. Le code de sortie 75 (« déjà en cours ») est traité comme un succès.
- **Écart** : `SCRAPE_FREQUENCY_HOURS` est supprimé ; les horaires vivent dans le timer.
- `utils/lock.py` : verrou `fcntl` sur `data/.scrape.lock`, pris par `scrape` et `enrich`. Le bouton de l'UI le respecte.
- Mode `--unattended` : le captcha est notifié et attendu 10 min (3 min en manuel, avec notification aussi). Un blocage non résolu est mémorisé dans `data/.last_block.json`, et un run planifié saute ce site pendant 6 h. Un run manuel prévient mais continue.

### 13.5 — Temps de trajet : reporté
Le serveur OSRM public est un serveur de démonstration, avec une politique d'usage limitée ; Tisséo demande une clé d'API. À reprendre avec une instance OSRM locale (Docker) ou une clé Tisséo. Le score accepte déjà un critère supplémentaire via `SCORE_WEIGHTS`.

### Pour activer de ton côté
1. `cp .env.example .env`, renseigner `NTFY_TOPIC` (et installer l'appli ntfy), puis `python main.py notify-test`.
2. `systemctl --user link "$PWD/deploy/scraper.service" "$PWD/deploy/scraper.timer"` puis `systemctl --user enable --now scraper.timer`.
3. Vérifier `systemctl --user show-environment | grep DISPLAY` : Chrome a besoin de la session graphique.
