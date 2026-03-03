# Scrapper Annonces

## Objectif

Ce projet automatise la recherche d'appartements en agrégeant des annonces immobilières provenant de différentes sources.

L'idée est de gagner du temps face à la multitude d'offres et à la réactivité nécessaire sur le marché locatif, en remplaçant la recherche manuelle fastidieuse par des robots intelligents.

---

## État actuel (v0.5 — post-Sprint 2)

Le projet contient une implémentation fonctionnelle pour un cas d'usage spécifique : **Toulouse (secteur ENAC)**.

👉 **[Voir le module Toulouse Rent Scraper](./toulouse_rent_scraper/README.md)**

Ce module permet de :

- Scraper **SeLoger** et **LeBonCoin** avec contournement des protections anti-bot.
- Filtrer automatiquement par prix (≤ 500€) et distance de l'ENAC (≤ 10 km).
- Stocker les résultats en base SQLite locale avec déduplication.
- Consulter les annonces via une **interface web Flask** (`--ui`).
- Exporter en **CSV ou JSON** (`--export`).
- Générer des **rapports Markdown** automatiques après chaque scrape.
- Vérifier la validité des liens via **Playwright** (`--check-links`).

---

## Réalisé

### Interface Web Flask

Interface responsive pour consulter, filtrer et supprimer les annonces, accessible sur `http://localhost:5000` via `python main.py --ui`.

### Export & Rapports

- Rapports Markdown auto-générés après chaque exécution (`nouvelles_annonces.md`, `toutes_les_annonces.md`).
- Export CSV/JSON via `--export csv` ou `--export json`.

---

## Vision & Roadmap

### 1. Système Adaptatif

Configuration dynamique des critères (ville, budget, surface, points d'intérêt) sans modifier le code source.

### 2. Enrichissement des données (Sprint 3)

Extraction des détails complets de chaque annonce : surface, DPE, charges, description, photos.

### 3. Nouveaux scrapers (Sprint 4)

Intégration de PAP.fr.

### 4. Système de scoring (Sprint 5)

Score 0-100 par annonce selon distance, prix, surface, DPE, meublé.

### 5. API REST & Dashboard

FastAPI + Streamlit pour une visualisation avancée et un accès programmatique.

---

*Projet personnel en cours de développement.*
