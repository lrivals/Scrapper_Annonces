# Sprint 5 — Rapports Markdown avancés

**Objectif** : Transformer les rapports Markdown en documents de qualité professionnelle, exploitables pour la prise de décision rapide (comparer, filtrer, prioriser les annonces).

**Durée estimée** : 3-4 jours

**Prérequis** : Sprint 3 terminé (données enrichies disponibles).

---

## Problèmes actuels des rapports

1. **Manque de données** : seuls titre, prix, distance et lien sont affichés
2. **Pas de classement intelligent** : tri par prix uniquement
3. **Pas de comparaison** : impossible de voir l'évolution entre deux runs
4. **Pas de score** : difficile de prioriser les annonces
5. **Format unique** : un seul niveau de détail
6. **Pas de statistiques** : aucun résumé analytique

---

## Tâches

### 5.1 Rapport enrichi avec données détaillées (Priorité: Haute | Effort: M)

**Actions** :
- Refactorer `reporting/generator.py` pour exploiter les données enrichies (Sprint 3)
- **`nouvelles_annonces.md`** — format amélioré pour chaque annonce :
  ```markdown
  ## Studio meublé Rangueil ⭐ 85/100

  | Critère | Détail |
  |---------|--------|
  | Prix | 380 € CC |
  | Surface | 22 m² |
  | Pièces | 1 |
  | Distance ENAC | 1.2 km |
  | Meublé | Oui |
  | DPE | C |
  | Source | LeBonCoin (particulier) |
  | Publié le | 08/02/2026 |

  > Description courte (150 premiers caractères)...

  [Voir l'annonce](https://...)
  ```
- Inclure les 3 premières photos (liens Markdown)
- Tronquer la description à 150 caractères (version courte)

**Critère de validation** : Le rapport affiche surface, pièces, DPE, meublé quand disponibles.

---

### 5.2 Système de scoring des annonces (Priorité: Haute | Effort: M)

**Actions** :
- Créer `filters/scoring.py` :
  - Fonction `compute_score(annonce: dict) -> int` (score 0-100)
  - Critères pondérés :
    | Critère | Poids | Logique |
    |---------|-------|---------|
    | Distance ENAC | 30% | < 2km = 30pts, 2-5km = 20pts, 5-10km = 10pts |
    | Prix | 25% | < 350€ = 25pts, 350-400€ = 20pts, 400-450€ = 15pts |
    | Surface | 15% | > 25m² = 15pts, 20-25m² = 10pts, < 20m² = 5pts |
    | Meublé | 10% | Oui = 10pts, Non = 0pts |
    | DPE | 10% | A-C = 10pts, D = 5pts, E-G = 0pts |
    | Particulier | 10% | Particulier = 10pts, Agence = 5pts |
  - Stocker le score en DB (colonne `score INTEGER`)
- Trier les rapports par score décroissant (meilleures annonces en premier)
- Afficher le score avec emoji : ⭐ > 80, ✅ > 60, ⚠️ > 40, ❌ < 40

**Critère de validation** : Chaque annonce a un score, les rapports sont triés par pertinence.

---

### 5.3 Rapport comparatif (diff entre runs) (Priorité: Haute | Effort: M)

**Actions** :
- Créer un nouveau rapport `rapport_comparatif.md` :
  - Section **Nouvelles annonces** (apparues depuis le dernier run)
  - Section **Annonces disparues** (URLs qui ne sont plus en ligne, si Sprint 1.5 implémenté)
  - Section **Évolution** :
    - Nombre d'annonces ajoutées vs supprimées
    - Évolution du prix moyen
    - Nouveau quartier représenté ?
- Stocker les métriques de chaque run dans `stats_history` (cf Sprint 2.4)
- Format condensé adapté à une lecture rapide (< 30 secondes)

**Critère de validation** : Après 2 runs successifs, le rapport comparatif montre les différences.

---

### 5.4 Rapport par quartier (Priorité: Moyenne | Effort: M)

**Actions** :
- Créer `rapport_quartiers.md` :
  - Grouper les annonces par quartier/commune
  - Pour chaque quartier :
    - Nombre d'annonces disponibles
    - Prix moyen / min / max
    - Distance moyenne à l'ENAC
    - Top 3 meilleures annonces (par score)
  - Classement des quartiers par rapport qualité/prix
- Extraction du quartier depuis `location_raw` :
  - Parser les formats : "Rangueil, Toulouse (31000)", "Toulouse 31000", "Ramonville-Saint-Agne"
  - Normalisation (majuscules, variantes)
  - Créer `geo/quartier_parser.py`

**Critère de validation** : Le rapport liste au moins 5 quartiers avec stats.

---

### 5.5 Export PDF des rapports (Priorité: Moyenne | Effort: S)

**Actions** :
- Convertir les rapports Markdown en PDF pour partage facile
- Utiliser `markdown2` + `weasyprint` (ou `md-to-pdf` via Node)
- Ajouter option CLI `--pdf` :
  ```bash
  python main.py --all --pdf   # Génère aussi les PDFs
  ```
- PDFs générés dans `reports/` (gitignored)
- Mise en page : en-tête avec logo/titre, pied de page avec date

**Critère de validation** : `python main.py --pdf` génère des PDFs lisibles et bien formatés.

---

### 5.6 Rapport "Top 10" résumé rapide (Priorité: Moyenne | Effort: S)

**Actions** :
- Créer `top10.md` — rapport ultra-condensé :
  ```markdown
  # Top 10 Annonces — 09/02/2026

  1. ⭐ 92 | 350€ | 25m² | 1.2km | Rangueil | [lien](...)
  2. ⭐ 88 | 380€ | 22m² | 0.8km | Ramonville | [lien](...)
  3. ✅ 75 | 400€ | 20m² | 2.1km | Saouzelong | [lien](...)
  ...

  📊 120 annonces en base | Prix moyen: 425€ | Nouvelles aujourd'hui: 3
  ```
- Une ligne par annonce, format scannable en 10 secondes
- Idéal pour notification Telegram (Sprint 1.3) : envoyer le Top 10

**Critère de validation** : Le fichier `top10.md` tient sur un écran et permet de choisir en 10 secondes.

---

## Résumé

| # | Tâche | Priorité | Effort | Dépendance |
|---|-------|----------|--------|------------|
| 5.1 | Rapport enrichi détaillé | Haute | M | Sprint 3 |
| 5.2 | Système de scoring | Haute | M | Sprint 3 |
| 5.3 | Rapport comparatif (diff) | Haute | M | — |
| 5.4 | Rapport par quartier | Moyenne | M | — |
| 5.5 | Export PDF | Moyenne | S | 5.1 |
| 5.6 | Rapport Top 10 | Moyenne | S | 5.2 |

**Légende effort** : S = ~1-2h | M = ~3-5h | L = ~1-2j

---

## Structure cible après Sprint 5

```
toulouse_rent_scraper/
├── reporting/
│   ├── generator.py          # Refactoré — rapports enrichis
│   └── exporter.py           # Sprint 1 — CSV/JSON
├── filters/
│   ├── price_and_distance.py
│   └── scoring.py            # NOUVEAU — score 0-100
├── geo/
│   ├── distance.py
│   └── quartier_parser.py    # NOUVEAU — extraction quartier
├── reports/                   # Générés automatiquement
│   ├── nouvelles_annonces.md  # Enrichi
│   ├── toutes_les_annonces.md # Enrichi
│   ├── rapport_comparatif.md  # NOUVEAU
│   ├── rapport_quartiers.md   # NOUVEAU
│   ├── top10.md               # NOUVEAU
│   └── *.pdf                  # NOUVEAU
└── tests/
    ├── test_scoring.py        # NOUVEAU
    └── test_quartier_parser.py # NOUVEAU
```

---

## Ordre d'exécution recommandé des sprints

```
Sprint 1 (Notifications & Export)
    ↓
Sprint 3 (Enrichissement)  ←→  Sprint 4 (PAP.fr)   [parallélisables]
    ↓
Sprint 5 (Rapports avancés)
    ↓
Sprint 2 (API & Dashboard)  [bénéficie de toutes les données enrichies]
```

Le Sprint 2 (API/Dashboard) est volontairement repoussé en dernier car il bénéficiera de toutes les données enrichies, du scoring, et des rapports avancés pour offrir un dashboard complet dès sa mise en place.
