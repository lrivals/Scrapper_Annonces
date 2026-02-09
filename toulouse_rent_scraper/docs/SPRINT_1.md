# Sprint 1 — Notifications & Export

**Objectif** : Rendre le scraper autonome et actionnable sans consultation manuelle des rapports.

**Durée estimée** : 1 semaine

---

## Tâches

### 1.1 Fix parsing prix SeLoger (Priorité: Haute | Effort: S)

**Problème** : Certaines annonces SeLoger remontent avec des prix aberrants (11€, 12€). Le parser extrait un mauvais nombre depuis le texte brut. (c'est aussi possible que ce soit des garage ou d'autres annonces déguisées ignorer annonces en dessousd'un certain prix 200?)

**Actions** :
- Analyser le HTML capturé des cartes SeLoger avec `debug_card_html.py`
- Identifier le format exact du prix dans les sélecteurs `data-testid`
- Corriger le regex/parser dans `scrapers/seloger.py`
- Ajouter des tests unitaires couvrant les cas limites SeLoger (prix avec `/mois`, prix en texte libre, prix avec espaces insécables)
- Purger les annonces à prix invalide de la DB existante

**Critère de validation** : Aucune annonce avec prix < 50€ ne passe le filtre.

---

### 1.2 Export CSV/JSON (Priorité: Haute | Effort: S)

**Problème** : Les rapports Markdown ne sont pas exploitables par d'autres outils (tableur, scripts, API).

**Actions** :
- Ajouter une option CLI `--export csv` et `--export json` dans `main.py`
- Créer `reporting/exporter.py` avec deux fonctions :
  - `export_csv(annonces, output_path)` — export avec en-têtes (prix, distance, titre, URL, date, source)
  - `export_json(annonces, output_path)` — export JSON structuré
- Les fichiers sont générés dans `reports/` (déjà gitignored)
- Ajouter des tests unitaires pour les deux formats

**Critère de validation** : `python main.py --export csv` génère un fichier CSV valide importable dans Excel/LibreOffice.

---

### 1.3 Notifications Telegram (Priorité: Haute | Effort: M)

**Problème** : Il faut consulter manuellement les rapports après chaque run. Pas d'alerte en temps réel.

**Actions** :
- Créer un bot Telegram via @BotFather, stocker le token dans `.env`
- Créer `notifications/telegram.py` :
  - Fonction `send_telegram_summary(new_annonces: list)`
  - Message formaté : titre, prix, distance ENAC, lien cliquable
  - Regroupement si > 10 annonces (résumé + "voir le rapport complet")
- Ajouter `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `config.py` (lecture depuis `.env`)
- Intégrer l'appel dans `main.py` après la génération des rapports
- Ajouter une option CLI `--no-notify` pour désactiver

**Dépendances** : `python-telegram-bot` ou appel direct API HTTP (plus léger).

**Critère de validation** : Après un run avec nouvelles annonces, un message Telegram est reçu avec les détails.

---

### 1.4 Notification email SMTP (Priorité: Moyenne | Effort: S)

**Problème** : Alternative à Telegram pour ceux qui préfèrent l'email.

**Actions** :
- Créer `notifications/email.py` :
  - Fonction `send_email_digest(new_annonces: list)`
  - Template HTML avec tableau des annonces (prix, titre, lien, distance)
- Configuration SMTP dans `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`)
- Option CLI `--notify email` / `--notify telegram` / `--notify all`
- Utiliser `smtplib` + `email.mime` (stdlib, pas de dépendance)

**Critère de validation** : Email reçu avec le digest HTML après un run.

---

### 1.5 Purge des annonces expirées (Priorité: Moyenne | Effort: M)

**Problème** : La DB accumule des annonces dont les URLs ne sont plus valides (supprimées par le propriétaire, expirées).

**Actions** :
- Créer `storage/cleaner.py` :
  - Fonction `check_expired_annonces()` — vérifie les URLs en base (HEAD request)
  - Marquer les annonces expirées (ajout colonne `status` : `active` / `expired`)
  - Migration DB automatique pour la nouvelle colonne
- Ajouter une option CLI `--purge` pour lancer le nettoyage
- Rate limiting : max 1 requête/seconde pour éviter le ban
- Exclure les annonces expirées des rapports

**Critère de validation** : `python main.py --purge` marque les annonces 404 comme expirées, elles disparaissent des rapports.

---

### 1.6 Tests notifications (Priorité: Moyenne | Effort: S)

**Actions** :
- Tests unitaires pour `notifications/telegram.py` avec mock de l'API HTTP
- Tests unitaires pour `notifications/email.py` avec mock SMTP
- Tests pour `reporting/exporter.py` (CSV valide, JSON valide)
- Tests pour `storage/cleaner.py` avec mock des requêtes HTTP

**Critère de validation** : Couverture > 80% sur les nouveaux modules, `pytest tests/ -v` tout vert.

---

## Résumé

| # | Tâche | Priorité | Effort | Dépendance |
|---|-------|----------|--------|------------|
| 1.1 | Fix parsing prix SeLoger | Haute | S | — |
| 1.2 | Export CSV/JSON | Haute | S | — |
| 1.3 | Notifications Telegram | Haute | M | .env config |
| 1.4 | Notification email SMTP | Moyenne | S | — |
| 1.5 | Purge annonces expirées | Moyenne | M | — |
| 1.6 | Tests notifications | Moyenne | S | 1.2, 1.3, 1.4, 1.5 |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure cible après Sprint 1

```
toulouse_rent_scraper/
├── ...
├── notifications/         # NOUVEAU
│   ├── __init__.py
│   ├── telegram.py
│   └── email.py
├── reporting/
│   ├── generator.py
│   └── exporter.py        # NOUVEAU
├── storage/
│   ├── sqlite.py
│   └── cleaner.py          # NOUVEAU
└── tests/
    ├── test_notifications.py  # NOUVEAU
    └── test_exporter.py       # NOUVEAU
```
