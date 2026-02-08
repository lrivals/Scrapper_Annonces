# 🏢 Scrapper Annonces

## 🎯 Objectif
Ce projet a pour but d'optimiser et d'automatiser la recherche d'appartements en agrégeant des annonces immobilières provenant de différentes sources.

L'idée est de gagner du temps face à la multitude d'offres et à la réactivité nécessaire sur le marché locatif, en remplaçant la recherche manuelle fastidieuse par des robots intelligents.

---

## 🚀 État actuel (MVP)
Actuellement, le projet contient une implémentation fonctionnelle pour un cas d'usage spécifique : **Toulouse (secteur ENAC)**.

👉 **[Voir le module Toulouse Rent Scraper](./toulouse_rent_scraper/README.md)**

Ce module permet déjà de :
- Scraper des sites comme SeLoger (avec contournement des protections anti-bot).
- Filtrer automatiquement par prix et géolocalisation précise.
- Stocker les résultats en base de données locale.

---

## 🔮 Vision & Roadmap
À terme, ce projet a vocation à devenir une plateforme générique et adaptative ("SaaS personnel") :

### 1. Système Adaptatif
Configuration dynamique des critères (ville, budget, surface, points d'intérêt) sans avoir à modifier le code source.

### 2. Interface Web
Développement d'une petite interface utilisateur (Web UI) permettant de :
- Saisir ses besoins (ex: "Paris 15ème, < 1000€, proche métro").
- Lancer le scraper à la demande.
- Visualiser les résultats sous forme de tableau de bord.

### 3. Export & Rapports
- Possibilité de télécharger une sélection d'annonces.
- Formats de sortie : `.txt` ou `.md` (Markdown) contenant les descriptions, les prix et les liens directs pour faciliter la lecture hors ligne ou le partage.

---

*Projet personnel en cours de développement.*