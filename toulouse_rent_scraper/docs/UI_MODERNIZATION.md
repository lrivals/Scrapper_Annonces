# Plan de Modernisation de l'UI

Ce document détaille les améliorations esthétiques et ergonomiques prévues pour l'interface de navigation des annonces.

## Objectifs
Transformer l'interface actuelle (tableau Flask basique) en un dashboard moderne, visuel et premium.

## Changements Proposés

### 1. Grille de Cartes (Card Grid)
- **Remplacement du tableau** par une grille interactive.
- **Visualisation accrue** : Chaque carte affichera les informations clés de manière hiérarchisée.
- **Support des images** : Préparation de l'affichage des photos (colonne `photos` en DB).

### 2. Design "Premium"
- **Palette de couleurs** : Utilisation de tons Indigo, Slate et de contrastes doux.
- **Glassmorphism** : Effets de transparence et de flou sur le header et la barre de filtres.
- **Typographie** : Utilisation de polices système modernes (`Inter`, `system-ui`).

### 3. Expérience Utilisateur (UX)
- **Animations** : Transitions fluides au survol des cartes.
- **Réactivité** : Layout adaptatif via CSS Grid pour une consultation optimale sur mobile et tablette.
- **Filtres améliorés** : Barre de recherche plus compacte et élégante.

## Plan d'Action
1. **Refonte du CSS** : Définition des tokens de design et du système de grille.
2. **Mise à jour du Template** : Modification du `TEMPLATE` HTML dans `ui.py`.
3. **Tests de Navigation** : Vérification du comportement sur différents supports.

---
*Date de création : 2026-03-02*
