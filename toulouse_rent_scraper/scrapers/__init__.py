# scrapers/__init__.py
# =========================
# Registre des scrapers — import paresseux : importer ce package ne charge
# pas Playwright (l'UI et les tests doivent fonctionner sans navigateur).
# =========================

from importlib import import_module

# clé CLI → "module:Classe"
SCRAPER_PATHS = {
    "seloger": "scrapers.seloger:SeLogerScraper",
    "leboncoin": "scrapers.leboncoin:LeBonCoinScraper",
}


# clé CLI → nom du site tel que stocké en base (colonne `site`)
SITE_NAMES = {
    "seloger": "SeLoger",
    "leboncoin": "LeBonCoin",
}


def get_scraper_class(key: str):
    """Importe et retourne la classe du scraper `key` (ex. 'leboncoin')."""
    module_name, class_name = SCRAPER_PATHS[key].split(":")
    return getattr(import_module(module_name), class_name)
