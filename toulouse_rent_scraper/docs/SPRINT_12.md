# Sprint 12 — Refactor & sécurité

> **Date** : 2026-11-03
> **Statut** : ✅ Terminé — un critère reste à valider lors d'un vrai scraping (voir bilan)
> **Origine** : [AUDIT_2026-11.md](AUDIT_2026-11.md) — A1 à A7, S1 à S3, H1 à H3
> **Prérequis** : [Sprint 11](SPRINT_11.md) terminé (les tests ajoutés servent de filet)

## Objectif

Supprimer la duplication (Chrome, anti-bot), découper les fichiers monolithiques,
fiabiliser le stockage et sécuriser l'UI locale. Aucun changement de comportement
visible attendu, hors sécurité. Prépare le Sprint 4 (PAP.fr) et le Sprint 13
(exécution planifiée).

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 12.1 | `scrapers/browser.py` — session Chrome unique | ✅ | Port libre, attente active, binaire configurable |
| 12.2 | `scrapers/antibot.py` | ✅ | Détection + attente challenge |
| 12.3 | Découpage de `BaseScraper.scrape()` | ✅ | Réutiliser `_find_working_selector` |
| 12.4 | Stockage : migrations versionnées, index, historique de prix | ✅ | `PRAGMA user_version` |
| 12.5 | Découpage de l'UI | ✅ | Package `ui/`, templates Jinja |
| 12.6 | Sécurité de l'UI | ✅ | CSRF, redirect, logs |
| 12.7 | CLI clarifiée | ✅ | Sous-commandes |
| 12.8 | Hygiène du repo | ✅ | Config morte, deps, fichiers parasites, tests |

---

## 12.1 — `scrapers/browser.py` : session Chrome unique

Remplace le code dupliqué de `scrapers/base.py:344-367`, `scrapers/enricher.py:108-136` et `debug_card_html*.py`.

```python
@contextmanager
def chrome_session(headless: bool = False):
    """Lance Chrome (profil persistant) + connexion CDP. Yield (browser, page)."""
    port = _free_port() if CHROME_DEBUG_PORT == 0 else CHROME_DEBUG_PORT
    proc = subprocess.Popen([CHROME_BINARY, f"--remote-debugging-port={port}",
                             f"--user-data-dir={BROWSER_PROFILE_DIR}", ...])
    try:
        _wait_for_cdp(port, timeout=15)          # poll http://localhost:{port}/json/version
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield browser, page
            browser.close()
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
```

- `config.py` : `CHROME_BINARY` (défaut `shutil.which("google-chrome") or shutil.which("chromium")`), `CHROME_DEBUG_PORT = 9222`.
- Détecter un profil verrouillé (`SingletonLock` présent + Chrome déjà lancé) et lever une erreur explicite au lieu d'un timeout CDP.
- `HEADLESS_BROWSER` : soit branché ici (`--headless=new`), soit supprimé (DataDome bloque le headless — trancher et documenter).
- Utilisateurs : `BaseScraper.scrape()`, `enricher.enrich_annonces()`, `cleaner.check_links_playwright()`, scripts de debug.

**Tests** : `_free_port`, `_wait_for_cdp` (serveur HTTP local factice), erreur si binaire introuvable.

## 12.2 — `scrapers/antibot.py`

Fusionner `BaseScraper.is_page_blocked/wait_for_challenge` et `enricher._is_page_blocked/_wait_for_challenge` :

```python
BLOCKED_DOMAINS, CHALLENGE_MARKERS, BLOCK_TITLES = ...

def is_page_blocked(page, site_domain: Optional[str] = None) -> bool: ...
def wait_for_challenge(page, timeout_s=180, on_challenge: Callable | None = None) -> bool: ...
```

- `on_challenge` : hook appelé une fois au début de l'attente (utilisé au Sprint 13 pour notifier « captcha à résoudre »).
- Corriger le log de décompte (`remaining % 15 == 0` ne tombe presque jamais avec un pas de 3 s) → log toutes les 15 s mesurées.
- `BaseScraper` garde des méthodes surchargeables `blocked_domains()` / `challenge_markers()` qui délèguent au module.

## 12.3 — Découpage de `BaseScraper.scrape()`

Cible : `scrape()` < 40 lignes, orchestrant :

```python
def scrape(self):
    with chrome_session() as (browser, page):
        if not self._navigate_steps(page):          return self.results
        selector = self._find_working_selector(page) or self._retry_after_challenge(page)
        if not selector:                              self._dump_debug(page); return self.results
        self._scrape_current_page(page, selector, 1)
        self._paginate(page, selector)
    return self.results
```

- `_navigate_steps`, `_retry_after_challenge`, `_dump_debug` (écrit dans `LOG_DIR`, pas `logs/` relatif au cwd), `_paginate` (URLs directes ou bouton).
- Supprimer la boucle de sélecteurs dupliquée (`base.py:421-449`) au profit de `_find_working_selector`.
- Conserver `card.scroll_into_view_if_needed()` + pause (lazy-loading LBC, cf. mémoire projet).

**Tests** (`tests/test_base_scraper.py`) : scraper factice + `page` mockée → pagination stoppée à `MAX_PAGES_PER_SITE`, arrêt propre si bloqué.

## 12.4 — Stockage : migrations versionnées, index, historique de prix

**Fichiers** : `storage/sqlite.py` → `storage/db.py` (connexion + migrations), `storage/annonces.py` (CRUD), `storage/queries.py` (requêtes UI)

- **Migrations** : liste ordonnée de fonctions, appliquées selon `PRAGMA user_version` ; la migration 1 reprend l'état actuel (idempotente pour les bases existantes).
- **Connexion** : `get_connection()` active `PRAGMA journal_mode=WAL` (UI + scraping simultanés) et `row_factory = sqlite3.Row` ; context manager pour commit/close.
- **Index** : `annonces(status)`, `annonces(site)`, `annonces(price)`, `annonces(created_at)`.
- **Historique de prix** : table `price_history(annonce_id, price, seen_at)` alimentée par `insert_annonce` sur `new` et `updated` ; UI : « ↓ 30 € depuis le 12/10 ».
- **`storage/queries.py`** : `build_filters(args) -> (where_sql, params)` partagé par `/` et `/api/map-data` (supprime la duplication `ui.py:1008-1031` / `ui.py:1248-1269`), `list_annonces(filters, sort, order)`, `map_listings(filters)`, `get_annonces_by_ids(ids)`.
- Garder `ALLOWED_SORTS` comme liste blanche du `ORDER BY` (f-string actuelle `ui.py:1032`).

## 12.5 — Découpage de l'UI

```
ui/
  __init__.py      # create_app(), run_ui()
  routes.py        # vues Flask, sans SQL
  export.py        # génération du Markdown candidature
  templates/index.html
  static/app.css, app.js
```

- Le template inline devient `templates/index.html` (Jinja `render_template`).
- CSS et JS extraits en fichiers statiques.
- `main.py --ui` importe `ui.run_ui` (inchangé côté utilisateur).
- Mettre à jour la décision ROADMAP « Template HTML embarqué dans `ui.py` » (2026-03-02).

## 12.6 — Sécurité de l'UI

- **CSRF** : token aléatoire par session (`secrets.token_urlsafe`) injecté dans chaque formulaire et en en-tête `X-CSRF-Token` pour les appels `fetch` ; `@app.before_request` refuse tout POST sans token valide (403). `app.secret_key` généré au démarrage ou lu depuis `.env`. Alternative sans dépendance : vérifier aussi `Origin`/`Referer` == hôte local.
- **Open redirect** : `_safe_back(back)` n'accepte que les chemins relatifs commençant par `/` sans `//` ; sinon `/`.
- **Logs** : retirer `logging.basicConfig(level=DEBUG)` ; utiliser `utils/logger.setup_logger("ui")` comme le reste du projet.
- `/clear-db` : exiger un champ de confirmation (`confirm=VIDER`) côté serveur, pas seulement un `confirm()` JS.
- `/start-scraping` : rediriger stdout/stderr du sous-processus vers `LOG_DIR/ui_scraping.log` et l'afficher (tail) dans l'UI.

**Tests** (`tests/test_ui.py`, `app.test_client()`) : POST sans token → 403 ; `back=https://evil.com` → redirection `/` ; filtres combinés OK.

## 12.7 — CLI clarifiée

Passer à des sous-commandes (compatibles avec l'existant via alias si besoin) :

```
python main.py scrape [--site seloger|leboncoin] [--enrich] [--export csv|json]
python main.py enrich [--site …] [--limit N]
python main.py check-links [--limit N]
python main.py ui [--port 5000]
python main.py notify-test          # Sprint 13
```

- Supprime `default=True` + le test `"--all" in sys.argv` (`main.py:21`, `main.py:43`).
- Extraire la boucle de traitement (`main.py:109-188`) dans `pipeline.py::process_annonces(site, raw) -> RunStats` (dataclass) — réutilisée par le scraping depuis l'UI et les notifications.
- `scraper_map` construit depuis `scrapers.SCRAPERS` (clé = `site_name().lower()`), plus de double déclaration.
- Mettre à jour `README.md` et `/start-scraping`.

## 12.8 — Hygiène du repo

- **Config morte** : supprimer ou brancher `DEDUP_KEYS` (fait en 11.6), `PROPERTY_TYPES`, `TARGET_DISTRICTS`, `USER_AGENT`, `USE_STEALTH_MODE`, `SAVE_RAW_HTML` ; `SCRAPE_FREQUENCY_HOURS` est branché au Sprint 13.
- **`requirements.txt`** : `+ requests`, `− playwright-stealth`, épingler les versions majeures ; ajouter `requirements-dev.txt` (pytest, pytest-cov).
- **Tests sans navigateur** : `scrapers/__init__.py` ne doit plus importer Playwright au chargement (registre lazy : `SCRAPERS = {"seloger": "scrapers.seloger:SeLogerScraper", …}`), ou `tests/conftest.py` avec `pytest.importorskip("playwright")` pour les tests de scrapers uniquement. `tests/test_filters.py` ne doit dépendre que de `filters/` et `geo/`.
- **Fichiers parasites** : supprimer `=3.0.0`, `plan-implementation.txt` ; déplacer `debug_*.py` et `test_seloger_*.py`/`test_quick_seloger.py` vers `scripts/debug/` ; archiver `AMELIORATIONS.md` dans `docs/archive/`.
- **`.gitignore`** : unifier les deux fichiers (racine + projet) ; ignorer `Docrech/` (dossiers de candidature personnels).

---

## Critères d'acceptation

- [x] `grep -rn "9222\|google-chrome" --include=*.py .` ne renvoie que `config.py` — plus `scrapers/browser.py`, qui contient la liste des binaires candidats (c'est son rôle) et les vieux scripts `scripts/debug/explore_*` (obsolètes, conservés pour référence).
- [x] Une seule implémentation de `is_page_blocked` (`scrapers/antibot.py`) ; `BaseScraper.is_page_blocked` ne fait que déléguer, avec le domaine du site.
- [x] `ui/` ne contient aucune requête SQL.
- [x] `pytest` vert **sans** Playwright installé : 194 passés, 1 ignoré (simulation par un faux paquet `playwright` qui lève `ImportError`) — résultat identique avec Playwright.
- [x] POST sans jeton sur `/clear-db` → 403 (vérifié en test et dans un navigateur).
- [ ] Un run de scraping complet produit les mêmes compteurs qu'avant le refactor — **à valider au prochain scraping réel** (non lancé : Chrome + DataDome). L'orchestration est couverte par `tests/test_base_scraper.py` et `tests/test_pipeline.py`.

## Bilan d'implémentation (2026-11-03)

Tests : **195 passés, 1 ignoré** (136 avant le sprint). Nouveaux fichiers de test : `test_browser.py`, `test_base_scraper.py`, `test_cli.py`, `test_pipeline.py` ; `test_ui.py` étendu (CSRF, redirections, historique de prix).

### Écarts par rapport au plan

| Plan | Réalisé | Raison |
|---|---|---|
| `storage/sqlite.py` → `db.py` + `annonces.py` + `queries.py` | `sqlite.py` conservé (connexion + écritures), ajout de `migrations.py` et `queries.py` | Une douzaine de modules et les fixtures de test importent `storage.sqlite` ; le découpage en trois n'apportait rien de plus que ces deux ajouts. |
| `HEADLESS_BROWSER` « branché ou supprimé » | Supprimé | DataDome bloque le headless ; le scraping exige un vrai Chrome. Seul `check-links` reste en Chromium headless (décision du 2026-03-02). |
| `check-links` sur `chrome_session` | Chromium headless séparé, mais `USER_AGENT` repris de la config | Vérifier des liens n'a pas besoin du profil persistant, et ne doit pas le verrouiller pendant un scraping. |
| CSRF « token + éventuellement Origin » | Jeton de session (formulaire ou en-tête `X-CSRF-Token`) + cookie `SameSite=Strict` | Suffisant pour une UI locale ; pas de dépendance ajoutée. |
| Sous-commandes « ou alias » | Sous-commandes + traduction automatique de l'ancienne syntaxe, avec avertissement | Les habitudes (`--seloger`, `--ui`) et la doc existante restent valables. |
| `scripts/debug/` : déplacer `test_seloger_*.py` | Renommés `explore_seloger_*.py`, marqués obsolètes | Évite qu'on les prenne pour des tests ; contenu préservé. |
| Supprimer `plan-implementation.txt` | Archivé dans `docs/archive/` | C'est le plan initial du projet ; l'archiver ne coûte rien. |

### Ajouts non prévus

- **Historique de prix visible dans l'UI** : badge « ↓ 30 € » avec le prix initial au survol.
- **Bug du Sprint 11 corrigé** : le bouton « Restaurer » utilisait la classe `.btn-add-doc`, masquée hors mode document. Il était donc invisible. Trouvé lors de la vérification dans un navigateur ; il a maintenant sa propre classe et un test de non-régression.
- `chrome_session` refuse clairement un profil déjà utilisé (`SingletonLock`) ou un port occupé, au lieu d'échouer au bout du délai d'attente de connexion.
- `PlaywrightTimeoutError` est exposé par `scrapers/browser.py`, avec une classe de repli : les extracteurs n'importent plus Playwright.
- `.gitignore` unifié à la racine ; `Docrech/` (dossiers de candidature personnels) est ignoré.

### Fichiers

| Fichier | Changement |
|---|---|
| `scrapers/browser.py`, `scrapers/antibot.py` | Nouveaux |
| `scrapers/base.py` | `scrape()` ≈ 25 lignes : `_open_search`, `_navigate_steps`, `_goto_with_block_handling`, `_retry_after_challenge`, `_dump_debug` (dans `LOG_DIR`), `_paginate*` |
| `scrapers/enricher.py` | `chrome_session` + `antibot`, plus de code Chrome |
| `scrapers/__init__.py` | Registre paresseux `SCRAPER_PATHS`, `SITE_NAMES`, `get_scraper_class()` |
| `storage/migrations.py`, `storage/queries.py` | Nouveaux (migrations 1 = schéma existant, 2 = index + `price_history`) |
| `storage/sqlite.py` | `init_db` → migrations + WAL, `connect()`, `_record_price`, `get_price_history` |
| `ui.py` → `ui/` | Package : `__init__`, `routes`, `security`, `export`, `templates/`, `static/` |
| `pipeline.py` | Nouveau : `RunStats`, `process_annonces`, `run_scraping` |
| `main.py` | Sous-commandes + `translate_legacy_args` |
| `config.py`, `requirements*.txt`, `.gitignore`, `README.md` | Hygiène et documentation |

### Données

Base locale migrée (`user_version` = 2, WAL, 82 entrées d'historique de prix) après sauvegarde dans `data/annonces.bak-*-pre-sprint12.sqlite`.
