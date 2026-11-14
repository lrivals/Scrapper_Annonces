# PAP.fr — structure des pages (repérage du 2026-11-14)

Captures : `python scripts/debug/capture_cards_pap.py [URL]` et `… --detail URL_DE_FICHE` → `logs/debug_pap_*`.
Lecture : [`scrapers/detail_extractors/pap_html.py`](../scrapers/detail_extractors/pap_html.py) (HTML seul, testable sans navigateur).

## Accès

- **Cloudflare** : une requête sans navigateur reçoit `403` + « Just a moment… ». Le vrai Chrome au profil persistant passe sans vérification (accueil → recherche). Une vérification affichée est détectée (titre « Just a moment », « vérifiez que vous êtes humain ») et attend une résolution manuelle, comme le captcha LBC.
- Pas de DataDome.

## Recherche

URL Blagnac (profil `blagnac`, `pap_search_url`) :
`https://www.pap.fr/annonce/location-appartement-maison-blagnac-31700-g19307g43612`
(`g19307` = Blagnac, `g43612` = Toulouse ; `locations-…` sans type mélange bureaux, locaux, garages, colocations).

**Pas de pages numérotées : défilement infini.** Le site charge les pages `…-2`, `-3`… (HTML complet, slugs variables : `location-immobilier-…-3`, `a-louer-…-8`) et les ajoute à la page. `a#pagination-next` (caché) donne la suivante ; `data-infinite-scroll` porte `annonces_total` et `annonces_page`. Au-delà de la zone (`annonces_page: 0`, redirection `/proximite/…`), plus aucune carte n'est ajoutée.
→ Le scraper défile jusqu'à ce que le nombre de cartes ne bouge plus (`PAP_STABLE_SCROLLS` paliers), puis lit tout le HTML.

| Donnée | Sélecteur / motif |
|---|---|
| Carte | `div.search-list-item-alt` |
| Lien, id | `a.item-title[href="/annonces/appartement-blagnac-31700-r466100091"]` → id après `-r` |
| Type de bien | début du chemin : `appartement`, `maison` (gardés) ; `bureaux`, `local-…`, `garage-parking`, `colocation` (écartés) |
| Prix (CC) | `span.item-price` — « 1.080 € » (point des milliers) |
| Lieu | `span.h1` — « Blagnac (31700) », « Toulouse (31000) » (pas de quartier) |
| Pièces / chambres / m² | `ul.item-tags li` — « 2 pièces », « 1 chambre », « 35,21 m² » |
| DPE | `div.item-thumb-dpe-b` |
| Photos | `img[src^="https://cdn.pap.fr/photos/"]` du carrousel (diapositives `cloned` en double) |
| Description | `p.item-description` — résumé tronqué « … » (non gardé : la fiche est ouverte) |

## Fiche

| Donnée | Source |
|---|---|
| Surface, pièces, type, meublé, balcon/terrasse | JSON-LD `Product.additionalProperty` |
| Description, photos | JSON-LD `description`, `image[]` |
| Adresse | JSON-LD `address` : `streetAddress` (« Avenue de Cornebarrieu »), `addressLocality`, `postalCode` |
| Loyer CC, charges, dépôt | `<b>Loyer charges comprises</b>`, `<b>Dont charges</b>`, `<b>Dépôt de garantie</b>` + texte suivant |
| DPE / GES | `.energy-indice li.active`, `.ges-indice li.active` |
| Chambres | `ul.item-tags li` |
| GPS | `#carte_mappy[data-thunderforest]` → `{"center":["43.637980","1.380380"]}` — `exact` si une rue est donnée |
| Étage | non structuré : « rdc » / « 2e étage » cherché dans la description |
| Date de publication | absente |

Annonce en ligne = JSON-LD `Product` présent (`storage/cleaner.page_shows_expired`).
