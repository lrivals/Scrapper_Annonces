# Sprint 5 — Rapports avancés

**Objectif** : des rapports qui se lisent vite pour décider : les 10 meilleures annonces, les fiches
des nouvelles, ce qui a changé depuis le run précédent, les loyers par quartier, un PDF à partager.

**Statut** : ✅ Terminé — validé sur la base réelle, profil **Blagnac** (2026-11-14)

> Recadré le 2026-11-14 : le plan de février (score ENAC dans `filters/scoring.py`, weasyprint,
> `--all --pdf`) est remplacé par l'architecture actuelle. Le score existe depuis le 13.3 (`scoring.py`,
> par profil) ; le PDF passe par le Chromium de Playwright, déjà installé ; nouvelle sous-commande `report`.

---

## Tâches

| # | Tâche | Statut | Livrable |
|---|-------|--------|----------|
| 5.0 | Journal des runs | ✅ | Migration 11 : table `run_stats` (une ligne par run et par profil) + `annonces.expired_at` posé par trigger ; `storage/run_stats.py`, écrit à la fin de `pipeline.run_scraping` |
| 5.1 | Fiches enrichies | ✅ | `nouvelles_annonces.md` et `annonces_detaillees.md` : score + emoji, loyer CC, surface et €/m², pièces, distance, lieu, meublé, DPE, dépôt, source (particulier/agence), description coupée à 150 car., 1re photo ; tri par score |
| 5.2 | Score 0-100 | ✅ | Livré au Sprint 13.3 (`scoring.py`) — rien à refaire |
| 5.3 | Rapport comparatif | ✅ | `rapport_comparatif.md` : nouvelles, retirées, baisses de prix (`price_history`), évolution du nombre d'annonces, du loyer CC et du €/m² médians, nouveaux secteurs |
| 5.4 | Rapport par quartier | ✅ | `geo/quartier_parser.py` (formats des 4 sites) + `rapport_quartiers.md` : par commune, classement des quartiers, top 3 de chacun |
| 5.5 | Export PDF | ✅ | `reporting/pdf.py` : Markdown → HTML (petit convertisseur) → PDF par Chromium headless ; `report --pdf` |
| 5.6 | Top 10 + notification | ✅ | `top10.md` ; envoi selon `NOTIFY_TOP10` (`off` / `daily` / `run`) ou `report --send-top10` |
| 5.7 | Garde-fou CLI | ✅ | Une sous-commande inconnue (faute de frappe) est une erreur, plus jamais traduite en scraping |

## Rapports (`reports/<profil>/`)

| Fichier | Contenu | Lecture |
|---|---|---|
| `top10.md` | `1. ✅ 79 \| 595 € CC \| 46,7 m² \| T2 \| ≈ 1,6 km \| Blagnac — Pinot \| [lien]` + ligne marché | 10 s |
| `nouvelles_annonces.md` | Fiches des annonces rattachées au profil pendant ce run (ou les dernières 24 h avec `report`) | — |
| `rapport_comparatif.md` | Depuis la fin du run précédent : compteurs, médianes (± écart), nouvelles, baisses, retirées | 30 s |
| `rapport_quartiers.md` | Par commune ; quartiers d'au moins 2 annonces classés par score médian puis €/m² ; top 3 | — |
| `toutes_les_annonces.md` | Tableau de toutes les annonces, score d'abord | — |
| `annonces_detaillees.md` | Fiches de toutes les annonces dont la page a été lue | — |
| `rapports_<date>.pdf` | Top 10, nouvelles, comparatif et quartiers en un PDF (sans photos), pied de page date + n° de page | — |

Annonces prises en compte : actives, rattachées au profil, non exclues par ses critères (15.5),
hors doublons d'un autre site (11 / 15.8). Loyers comparés **charges comprises** (`scoring.rent_cc`).

## Validation (2026-11-14, base réelle, profil Blagnac)

- `report --profile blagnac --pdf` : 6 rapports + PDF de 35 pages (250 Ko) lisible.
  Top 10 cohérent avec l'UI (Pinot, Grand-Noble, PAP Colomiers/Blagnac) ; 381 annonces, loyer CC médian 817 €.
- Rapport par quartier : 3 communes, 24 quartiers de 2 annonces ou plus ; Grand-Noble/Pinot en tête
  (score médian 70, 13,9 €/m²).
- Le premier PDF pesait 24 Mo (photos embarquées en pleine résolution) : photos retirées du PDF.
- `report --send-top10` : Top 10 reçu sur Telegram (texte brut, un lien par annonce).
- Le comparatif « depuis le run précédent » se remplit à partir de deux runs journalisés : les runs du
  timer s'en chargent (avant, il compare aux dernières 24 h).
- Incident pendant la validation : `report` n'était pas dans la liste figée des sous-commandes, donc
  traduit en `scrape` par la compatibilité de l'ancienne syntaxe → un scraping SeLoger lancé par erreur
  (arrêté pendant l'échauffement, rien d'écrit). Corrigé par 5.7 et testé.

## Usage

```bash
python main.py report --profile blagnac                 # regénérer les rapports d'après la base
python main.py report --profile blagnac --pdf           # + PDF
python main.py report --since-hours 72                  # « nouvelles » = 3 derniers jours
python main.py report --profile blagnac --send-top10    # envoyer le Top 10 maintenant
```

Les rapports sont aussi regénérés à la fin de chaque `scrape`, puis le Top 10 est envoyé si
`NOTIFY_TOP10=daily` (premier run de la journée) ou `run` (chaque run) dans `.env`.

## Décisions

| Décision | Contexte |
|---|---|
| PDF par le Chromium de Playwright, pas weasyprint | Déjà installé ; weasyprint demande des bibliothèques système (Pango, Cairo) |
| Petit convertisseur Markdown maison | Les rapports n'utilisent qu'un sous-ensemble (titres, tableaux, listes, liens) ; pas de dépendance de plus |
| Pas de photos dans le PDF | Embarquées en pleine résolution : 24 Mo pour 47 annonces |
| Date de retrait par trigger SQLite | Couvre tous les chemins qui retirent une annonce (fiche, check-links, purge) sans les modifier |
| Quartiers : noms des sites normalisés, pas de référentiel | Chaque site découpe les quartiers à sa façon ; un référentiel officiel demanderait un géocodage par annonce |
| Top 10 désactivé par défaut | Évite un message de plus à chaque run ; `daily` recommandé |
