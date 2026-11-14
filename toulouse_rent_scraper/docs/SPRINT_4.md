# Sprint 4 — Nouvelle source : PAP.fr (Particulier à Particulier)

**Objectif** : ajouter PAP.fr comme source d'annonces de particuliers (sans frais d'agence) pour le profil **Blagnac**.

**Statut** : ✅ Terminé — validé en réel sur le profil Blagnac (2026-11-14)

> Recadré le 2026-11-14 : le plan de février (flags `--pap`, `mutually_exclusive_group`, budget étudiant ENAC)
> est remplacé par l'architecture actuelle — sous-commande `scrape --site pap`, modèle `Listing` (15.7),
> fiches ouvertes dans le pipeline (Sprint 16), profil Blagnac uniquement.

---

## Constats du repérage (4.1)

Détail : [pap_selectors.md](pap_selectors.md).

- **Cloudflare** : 403 sans navigateur → vrai Chrome au profil persistant (`BaseScraper`), pas d'`ApiScraper`.
- **Défilement infini, pas de pages** : on défile jusqu'à ce que la liste ne grandisse plus, puis on lit tout le HTML.
- La recherche « locations » mélange bureaux, locaux, garages, colocations → URL filtrée « appartement + maison » **et** filtre local sur le type (chemin de l'annonce).
- Cartes riches (prix CC, pièces, chambres, m², DPE, photos) ; la fiche ajoute JSON-LD `Product` (surface, meublé, balcon, adresse avec rue), charges, dépôt, DPE/GES et **GPS du plan**.

## Tâches

| # | Tâche | Statut | Livrable |
|---|-------|--------|----------|
| 4.1 | Repérage | ✅ | `scripts/debug/capture_cards_pap.py`, `docs/pap_selectors.md` |
| 4.2 | Configuration | ✅ | `SearchProfile.pap_search_url` / `pap_warmup_urls` (Blagnac), `PAP_*` dans `config.py` |
| 4.3 | Scraper | ✅ | `scrapers/pap.py` (`PAPScraper`) + `scrapers/detail_extractors/pap_html.py` ; `--site pap` |
| 4.4 | Fiche détaillée | ✅ | `scrapers/detail_extractors/pap_detail.py`, branché dans `enricher._extractor_for` |
| 4.5 | Tests | ✅ | `tests/test_pap.py` (18 tests, sans Playwright) |
| 4.6 | Intégration multi-sites | ✅ | Annonce en ligne (JSON-LD) dans `cleaner`, marqueurs Cloudflare dans `antibot`, adresse/balcon dans le panneau Détails, contrôle de santé sans la description tronquée |
| 4.7 | Validation réelle + timer | ✅ | Voir ci-dessous ; le timer (`scrape` sans `--site`) inclut PAP d'office |
| 4.8 | Budget de fiches PAP | ✅ | `DETAIL_VISITS_PER_RUN["PAP"] = 15` (sans lui, aucune fiche PAP n'était ouverte) |

## Validation réelle (2026-11-14, profil Blagnac)

- `scrape --site pap --profile blagnac` : 35 cartes chargées par défilement, **24 logements** gardés,
  0 rejet, 0 blocage Cloudflare ; 2 notifications Telegram (récapitulatifs).
- Ce run a révélé l'absence de budget de fiches pour PAP (« aucune annonce retenue à compléter ») → 4.8.
- `enrich --site pap --limit 5` : **5/5 fiches** lues (surface, pièces, charges, dépôt, DPE, meublé, rue),
  **5 repositionnées au GPS exact** : distances de 5,2 à 7,6 km au lieu de 7,33 km (centre de Toulouse).
- `quality` : aucun champ clé sous son seuil.

L'ancien 4.6 (flags indépendants `--seloger --pap`) est déjà couvert par `scrape --site X --site Y` (Sprint 12.7).

## Usage

```bash
python main.py scrape --site pap --profile blagnac            # PAP seul
python main.py scrape --site pap --site leboncoin --profile blagnac
python main.py enrich --site pap --limit 10                    # fiches PAP restantes
python scripts/debug/capture_cards_pap.py --detail URL         # re-capturer une fiche si le site change
```

## Décisions

| Décision | Contexte |
|---|---|
| Vrai Chrome, pas d'API | Cloudflare renvoie 403 aux requêtes sans navigateur |
| Défilement puis lecture du HTML complet | Les URLs des pages suivantes changent de slug ; défiler est le comportement humain normal |
| Lecture du HTML par regex dans un module pur | Testable sans navigateur, même approche que `seloger_json` |
| Prix de la carte = loyer CC (`charges_included=True`) | Vérifié sur les fiches (« Loyer charges comprises ») |
| GPS du plan `exact` seulement si une rue est donnée | Sinon le plan est centré sur la commune |
