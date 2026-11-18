# scrapers/smart_pagination.py
# =========================
# Pagination intelligente : ne lire que les pages qui peuvent contenir du nouveau.
#
# Toutes les recherches sont triées des plus récentes aux plus anciennes (LBC sort=time,
# SeLoger DateDesc, Bien'ici publication-desc). Quand une page ne contient plus que des
# annonces publiées avant le dernier passage de cette recherche (moins une marge), les
# pages suivantes sont plus anciennes encore et ont été lues au passage précédent : on
# s'arrête. Page sans dates exploitables : on s'arrête si toutes ses annonces sont déjà
# en base, sinon on continue (dans le doute, on lit).
#
# Un parcours complet (toutes les pages) est refait tous les SMART_FULL_SCAN_DAYS jours,
# ou s'il n'y a pas encore d'historique, pour revoir les prix des annonces plus anciennes.
# L'état n'est enregistré que si la recherche s'est terminée normalement (pas de blocage
# ni d'erreur) : un passage interrompu ne fait pas sauter de pages au suivant.
# =========================

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional

import config
from utils.logger import setup_logger

logger = setup_logger("pagination")

# Fin normale d'une recherche : « stale » = arrêt anticipé (pages suivantes déjà vues),
# « end » = plus de page, « max » = plafond MAX_PAGES_PER_SITE atteint
COMPLETE_STATUSES = ("stale", "end", "max")
FULL_STATUSES = ("end", "max")


def _state_path() -> Path:
    return Path(config.SEARCH_STATE_FILE)


def _read_state() -> Dict[str, Dict[str, str]]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse(stamp: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


def annonce_date(annonce: Dict) -> Optional[date]:
    """
    Date qui ordonne la recherche : `listed_at` (date de remontée LBC) si connue, sinon
    la date de publication lue dans le JSON de la recherche.
    """
    value = annonce.get("listed_at") or (annonce.get("details") or {}).get("published_at") \
        or annonce.get("published_at")
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class PaginationPlan:
    """Décide, page après page, si la suite d'une recherche (site, profil) mérite d'être lue."""

    def __init__(self, site_name: str, profile_key: str, now: Optional[datetime] = None,
                 force_full: bool = False):
        self.site_name = site_name
        self.key = f"{site_name}|{profile_key}"
        self.started_at = now or datetime.now()
        entry = _read_state().get(self.key) or {}
        self.last_scan_at = _parse(entry.get("last_scan_at"))
        self.last_full_scan_at = _parse(entry.get("last_full_scan_at"))

        self.reason: Optional[str] = None   # pourquoi le parcours est complet (logs)
        if not config.SMART_PAGINATION:
            self.reason = "pagination intelligente désactivée"
        elif force_full:
            self.reason = "parcours complet demandé"
        elif not self.last_scan_at or not self.last_full_scan_at:
            self.reason = "premier passage"
        elif self.started_at - self.last_full_scan_at > timedelta(days=config.SMART_FULL_SCAN_DAYS):
            self.reason = f"dernier parcours complet il y a plus de {config.SMART_FULL_SCAN_DAYS} jours"

    @property
    def full_scan(self) -> bool:
        return self.reason is not None

    @property
    def cutoff(self) -> Optional[date]:
        """Annonces datées d'avant ce jour : déjà vues au passage précédent."""
        if self.full_scan:
            return None
        return self.last_scan_at.date() - timedelta(days=config.SMART_PAGINATION_MARGIN_DAYS)

    def describe(self) -> str:
        if self.full_scan:
            return f"parcours complet ({self.reason})"
        return (f"arrêt dès qu'une page ne contient que des annonces d'avant le "
                f"{self.cutoff:%d/%m} (dernier passage le {self.last_scan_at:%d/%m %H:%M})")

    def stale_reason(self, annonces: Iterable[Dict], page_num: int, known=None) -> Optional[str]:
        """
        Raison de ne pas lire la page suivante, ou None pour continuer.
        `known(url) -> bool` : annonce déjà en base (pages sans dates).
        """
        if self.full_scan or page_num < config.SMART_PAGINATION_MIN_PAGES:
            return None
        annonces = list(annonces)
        if not annonces:
            return None   # page vide ou illisible : la pagination s'arrêtera d'elle-même
        dates = [d for d in (annonce_date(a) for a in annonces) if d]
        if len(dates) >= config.SMART_PAGINATION_DATED_RATIO * len(annonces):
            newest = max(dates)
            if newest < self.cutoff:
                return (f"annonces de la page {page_num} publiées au plus tard le {newest:%d/%m}, "
                        f"avant le dernier passage")
            return None
        if known is None:
            from storage.sqlite import annonce_exists as known
        if all(a.get("url") and known(a["url"]) for a in annonces):
            return f"toutes les annonces de la page {page_num} sont déjà connues"
        return None

    def record(self, status: str) -> bool:
        """Enregistre le passage s'il s'est terminé normalement. True si enregistré."""
        if status not in COMPLETE_STATUSES:
            return False
        state = _read_state()
        entry = state.get(self.key) or {}
        entry["last_scan_at"] = self.started_at.isoformat(timespec="seconds")
        if status in FULL_STATUSES:
            entry["last_full_scan_at"] = self.started_at.isoformat(timespec="seconds")
        state[self.key] = entry
        try:
            _state_path().parent.mkdir(parents=True, exist_ok=True)
            _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning(f"État de pagination non enregistré ({self.key}) : {e}")
            return False
        return True
