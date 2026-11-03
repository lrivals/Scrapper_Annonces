# Sprint 6 — Qualité des données (Doublons & Annonces supprimées)

**Objectif** : Fiabiliser la base de données en améliorant la gestion des doublons
et la détection des annonces supprimées sur les sites sources.

**Durée estimée** : 1 jour

**Prérequis** : Aucun (maintenance pure, indépendant des sprints 3-5)

---

## Problèmes résolus

1. **Doublons URL ignorés silencieusement** : un re-scraping ne mettait jamais à jour `scraped_at` ni le prix
2. **Patterns LBC manquants** : "le bien a déjà été vendu" non reconnu par `check_links_playwright`
3. **Doublons flous non détectés** : même bien listé deux fois (URL différente) invisible en DB
4. **Logs insuffisants** : impossible de savoir combien d'annonces étaient nouvelles vs déjà connues

---

## Tâches

### 6.1 Mise à jour des doublons au scraping (Priorité: Haute | Effort: XS)

**Fichier** : `storage/sqlite.py`

**Actions** :

- Modifier `insert_annonce()` : si l'URL existe → `UPDATE scraped_at` (et `price` si changé)
- Retourner `"new"` / `"updated"` / `"unchanged"` au lieu d'un bool
- Conserver le retour `"new"` pour les insertions réelles

**Critère de validation** : Scraper deux fois la même annonce → `scraped_at` mis à jour en DB.

**Statut** : ✅ Terminé

---

### 6.2 Détection de doublons flous (Priorité: Moyenne | Effort: S)

**Fichier** : `storage/sqlite.py`

**Actions** :

- Ajouter `find_potential_duplicates(annonce: dict) -> list` :
  - Requête SQL : même `site` + `price` entre `price-5` et `price+5` + URL différente
  - Filtrage Python : au moins 1 mot-clé de `location_raw` en commun (> 3 caractères)
- Appel dans `main.py` lors de chaque insertion avec log warning si match

**Critère de validation** : Deux annonces avec même prix et même quartier → warning affiché.

**Statut** : ✅ Terminé

---

### 6.3 Patterns LBC manquants (Priorité: Haute | Effort: XS)

**Fichier** : `storage/cleaner.py`

**Actions** : Ajouter dans `_EXPIRED_PATTERNS` :

- `"le bien a déjà été vendu"`
- `"l'annonceur a supprimé son annonce"`
- `"lien sur lequel vous avez cliqué peut être sectionné"`
- `"annonce introuvable"`
- `"cette annonce n'est plus disponible"`
- `"request interrupted"`

**Critère de validation** : `--check-links` sur une annonce LBC expirée → status = 'expired'.

**Statut** : ✅ Terminé

---

### 6.4 Logs post-scraping enrichis (Priorité: Moyenne | Effort: XS)

**Fichier** : `main.py`

**Actions** :

- Compteurs `new / updated / unchanged / duplicates_detected` par site et au global
- Affichage en fin de run :

```
[SeLoger] Nouvelles : 3 | Mises à jour : 38 | Inchangées : 1
⚠ 1 doublon potentiel détecté : "Studio Rangueil 350€" ↔ "Studio Rangueil 31400 355€"
```

**Critère de validation** : Lancement avec annonces existantes → stats correctes affichées.

**Statut** : ✅ Terminé

---

## Résumé

| # | Tâche | Priorité | Effort | Statut |
|---|-------|----------|--------|--------|
| 6.1 | Mise à jour doublons au scraping | Haute | XS | ✅ |
| 6.2 | Détection doublons flous | Moyenne | S | ✅ |
| 6.3 | Patterns LBC manquants | Haute | XS | ✅ |
| 6.4 | Logs post-scraping enrichis | Moyenne | XS | ✅ |

**Légende effort** : XS = < 1h | S = ~1-2h | M = ~3-5h | L = ~1-2j
