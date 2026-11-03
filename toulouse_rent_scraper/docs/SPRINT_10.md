# Sprint 10 — Vue Carte OpenStreetMap

> **Date** : 2026-03-25
> **Statut** : ✅ Terminé

## Objectif

Ajouter une vue carte interactive à l'interface Flask, permettant de visualiser
géographiquement les annonces filtrées, avec un marqueur pour la cible (ENAC)
et des marqueurs pour chaque appartement.

## Tâches

| # | Tâche | Statut | Notes |
|---|-------|--------|-------|
| 10.1 | Route `/api/map-data` | ✅ | JSON `{enac, listings[]}` avec coords via `geocoding_cache` |
| 10.2 | Intégration Leaflet.js | ✅ | CDN `leaflet@1.9.4`, tuiles OpenStreetMap (aucune clé API) |
| 10.3 | Boutons toggle Liste / Carte | ✅ | Header UI, CSS `.btn-view`, état actif visuel |
| 10.4 | Marqueur ENAC | ✅ | Point noir, popup « ENAC — 7 Av. Édouard Belin » |
| 10.5 | Marqueurs appartements | ✅ | Points verts, popup titre / prix / distance / lien |
| 10.6 | Gestion adresses non géocodées | ✅ | Compteur affiché sous la carte, pas de crash |

## Architecture

### Endpoint `/api/map-data`

```
GET /api/map-data?site=&status=&prix_min=&prix_max=
```

Retourne :

```json
{
  "enac": { "lat": 43.5643, "lon": 1.4800 },
  "listings": [
    {
      "id": 42,
      "title": "Studio Rangueil",
      "price": 420,
      "location_raw": "Rangueil",
      "distance_km": 1.3,
      "url": "https://...",
      "lat": 43.551,
      "lon": 1.469
    },
    ...
  ]
}
```

- Les coordonnées proviennent d'un **LEFT JOIN** sur `geocoding_cache`
  (table déjà peuplée lors des runs de scraping / enrichissement).
- Les annonces sans entrée dans le cache ont `lat: null, lon: null`
  — elles ne sont pas affichées sur la carte mais comptabilisées.
- Les filtres (`site`, `status`, `prix_min`, `prix_max`) sont identiques
  à ceux de la vue liste.

### Changements `ui.py`

| Zone | Modification |
|------|-------------|
| `<head>` | Ajout CSS + JS Leaflet (CDN) |
| `<style>` | Classes `.view-toggle`, `.btn-view`, `#map`, `#map-view` |
| Header | Boutons `☰ Liste` / `🗺 Carte` |
| Après `<main>` | `<div id="map-view">` caché par défaut |
| `<script>` | Fonctions `setView()` + `initMap()` (lazy-load au 1er clic) |
| Routes Flask | Nouvelle route `@app.route("/api/map-data")` |

## Décisions techniques

| Décision | Raison |
|----------|--------|
| Leaflet.js via CDN | Aucune dépendance Python, aucune clé API, OSM gratuit |
| LEFT JOIN `geocoding_cache` | Pas de nouvelle colonne en base — réutilise le cache existant |
| Lazy-load carte | La carte n'est initialisée qu'au 1er clic sur "Carte" pour ne pas ralentir le chargement initial |
| Icônes `L.divIcon` | Évite les fichiers d'images externes, personnalisables en CSS inline |
| Filtres synchronisés | `new URLSearchParams(window.location.search)` passe les filtres actifs au fetch |

## Corrections post-sprint (2026-03-26)

Trois bugs identifiés après relecture du code et corrigés dans `ui.py` :

| # | Bug | Correction |
| --- | --- | --- |
| C1 | **Carte grise au re-affichage** — Leaflet ne détecte pas le re-show du conteneur caché (`display:none` → visible) | Ajout de `_leafletMap.invalidateSize()` dans `setView()` quand la carte est déjà initialisée |
| C2 | **Vue carte perdue après filtrage** — La page se rechargeait toujours en vue liste après soumission du formulaire filtres | Champ `<input type="hidden" name="view" id="view-input">` dans le formulaire + auto-restore via `?view=map` dans l'URL au chargement |
| C3 | **Pas de feedback en cas d'erreur fetch** — Si `/api/map-data` échoue, le div `#map` restait vide silencieusement | Ajout d'un `.catch()` affichant un message dans `#map-ungeolocated` |
