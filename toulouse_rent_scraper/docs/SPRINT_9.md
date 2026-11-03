# Sprint 9 — Photos & Thumbnails

> **Statut** : ✅ Terminé
> **Date** : 2026-03-25
> **Version** : v0.7

---

## Objectif

Ajouter l'affichage des photos de chaque annonce dans l'interface web :

- Extraire une image miniature (thumbnail) dès le scraping initial (page de liste)
- Afficher cette miniature en haut de chaque carte dans l'UI
- Gérer un placeholder pour les annonces sans photo
- Conserver la compatibilité avec l'enrichissement Sprint 3 (qui écrase `photos` avec le tableau complet depuis la page détail)

---

## Tâches

| # | Tâche | Statut | Fichier |
|---|-------|--------|---------|
| 9.1a | Extraction thumbnail — SeLoger | ✅ | `scrapers/seloger.py` |
| 9.1b | Extraction thumbnail — LeBonCoin | ✅ | `scrapers/leboncoin.py` |
| 9.2 | Gestion `photos` dans `insert_annonce` | ✅ | `storage/sqlite.py` |
| 9.3 | Affichage photos dans l'UI (CSS + HTML) | ✅ | `ui.py` |
| 9.4 | Documentation sprint | ✅ | `docs/SPRINT_9.md`, `docs/ROADMAP.md` |

---

## Détails techniques

### 9.1 — Extraction thumbnail dans les scrapers de liste

Les scrapers `seloger.py` et `leboncoin.py` extraient désormais le premier `<img>` de chaque carte lors du scraping de la page de résultats.

**Sélecteurs utilisés :**

- **SeLoger** : `img[data-testid*="photo"], img[data-testid*="image"], img[src]`
- **LeBonCoin** : `img[src*="leboncoin"], img[src*="staticlbc"], img[data-src], img[src]`

Le thumbnail est stocké comme tableau JSON d'un élément : `["https://..."]` dans le champ `photos`.

Si aucune image n'est trouvée (carte sans visuel, scraping partiel), `photos` vaut `None`.

### 9.2 — Gestion dans `insert_annonce`

Deux cas gérés :

- **Nouvelle annonce** : le champ `photos` est inclus dans le `INSERT`
- **Annonce existante** : `UPDATE annonces SET photos = COALESCE(photos, ?) WHERE url = ?`
  → Si l'annonce a déjà été enrichie (Sprint 3), ses photos détaillées ne sont pas écrasées par le thumbnail

### 9.3 — Affichage dans l'UI (`ui.py`)

**Route `/`** : parsing du JSON `photos` pour extraire `thumbnail` (premier élément) avant rendu.

**CSS ajouté** :
- `.card-image` — zone image 180px en haut de la carte, `border-radius` haut seulement, `overflow: hidden`
- `.card-image img` — `object-fit: cover` + zoom doux au hover (`transform: scale(1.03)`)
- `.card-image-placeholder` — fond dégradé gris avec emoji maison centré

**HTML template** :
- `<a class="card-image">` cliquable vers l'annonce
- `<img loading="lazy" referrerpolicy="no-referrer">` pour les CDN SeLoger/LBC
- `onerror` inline pour fallback silencieux vers le placeholder si l'image est bloquée (Referer check)

---

## Notes

- Les CDNs SeLoger et LeBonCoin peuvent refuser les requêtes sans Referer valide → `referrerpolicy="no-referrer"` + `onerror` fallback
- L'enrichissement Sprint 3 écrase `photos` avec un tableau plus complet (5-10 images) — le thumbnail de la liste est conservé tant que l'enrichissement n'a pas tourné
- Les annonces déjà en base avant ce sprint n'ont pas de photos ; elles affichent le placeholder jusqu'au prochain scraping ou enrichissement
