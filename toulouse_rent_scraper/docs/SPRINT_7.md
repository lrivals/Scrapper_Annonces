# Sprint 7 — Mode Document & Cache Géocodage

**Objectif** : Améliorer l'interface de navigation avec un mode de sélection/export
d'annonces pour la constitution de dossiers de candidature, et fiabiliser le
géocodage en évitant les appels redondants à Nominatim.

**Durée estimée** : 1 jour

**Prérequis** : Sprint 2-ter (UI), Sprint 6 (SQLite)

---

## Problèmes résolus

1. **Pas de moyen d'exporter une sélection d'annonces** : impossible de constituer
   un dossier de candidature depuis l'interface sans copier-coller manuellement
2. **Géocodage redondant** : chaque lancement re-géocodait les mêmes adresses,
   provoquant des timeouts et des erreurs 403 Nominatim sur les runs successifs

---

## Tâches

### 7.1 Mode sélection dans l'UI (Priorité: Haute | Effort: M)

**Fichier** : `ui.py` (template TEMPLATE + CSS)

**Actions** :

- Bouton "Commencer document" dans le header → active `body.doc-mode-active`
- Bouton "+ Doc" par carte (masqué hors mode) → sélectionne/désélectionne une annonce
  - Carte sélectionnée : bordure verte + classe `in-doc`
  - Persistance de la sélection via `localStorage` (`documentIds`)
- Badge compteur visible dès qu'au moins 1 annonce est sélectionnée
- Boutons "Exporter ↓" et "Vider" affichés dynamiquement

**Critère de validation** : Activer le mode, sélectionner 2 annonces → compteur = 2,
bouton export visible, sélection persistante après rechargement de page.

**Statut** : ✅ Terminé

---

### 7.2 Export Markdown des annonces sélectionnées (Priorité: Haute | Effort: S)

**Fichier** : `ui.py` (route `/export-document`)

**Actions** :

- Route `POST /export-document` recevant une liste d'IDs JSON
- Requête SQLite pour récupérer les annonces dans l'ordre prix ASC
- Génération d'un fichier Markdown structuré (titre, prix, surface, localisation, lien)
- Réponse avec header `Content-Disposition: attachment` → téléchargement direct

**Format de sortie** :

```markdown
# Dossier de candidature — Annonces sélectionnées

## 1. [Titre de l'annonce]
- **Prix** : 750 €/mois
- **Surface** : 32 m²
- **Localisation** : Rangueil, Toulouse
- **Lien** : https://...
```

**Critère de validation** : Sélectionner 3 annonces, cliquer "Exporter ↓" →
fichier `.md` téléchargé avec les 3 annonces formatées.

**Statut** : ✅ Terminé

---

### 7.3 Cache géocodage persistant SQLite (Priorité: Moyenne | Effort: S)

**Fichier** : `geo/distance.py` + `storage/sqlite.py` (table `geocoding_cache`)

**Actions** :

- Nouvelle table `geocoding_cache (address TEXT PRIMARY KEY, latitude REAL, longitude REAL)`
  créée automatiquement par `init_db()`
- Avant chaque appel Nominatim : lookup cache (`SELECT` sur `address`)
- Après chaque appel réussi : insertion en cache (`INSERT OR REPLACE`)
- `time.sleep(1.0)` systématique après chaque appel Nominatim (respect ToS 1 req/s)

**Critère de validation** : Lancer deux fois avec les mêmes annonces → le second run
ne fait aucun appel réseau Nominatim (logs `Cache hit géocodage`).

**Statut** : ✅ Terminé

---

## Résumé

| # | Tâche | Priorité | Effort | Statut |
|---|-------|----------|--------|--------|
| 7.1 | Mode sélection UI | Haute | M | ✅ |
| 7.2 | Export Markdown (`/export-document`) | Haute | S | ✅ |
| 7.3 | Cache géocodage SQLite | Moyenne | S | ✅ |

**Légende effort** : XS = < 1h | S = ~1-2h | M = ~3-5h | L = ~1-2j
