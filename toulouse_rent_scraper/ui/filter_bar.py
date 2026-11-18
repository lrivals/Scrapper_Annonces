# ui/filter_bar.py
# =========================
# Barre d'outils de la liste : puces des filtres actifs, filtres rapides et menu de tri,
# calculés à partir de la query string (aucune route ni paramètre nouveau).
# =========================

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlencode

from storage.queries import ListingFilters

# Paramètres d'affichage ponctuels, jamais propagés dans les liens
TRANSIENT_PARAMS = ("flash", "flash_msg")
FILTER_PARAMS = tuple(ListingFilters.__dataclass_fields__)

STATUS_LABELS = {"active": "Actives", "expired": "Expirées", "hidden": "Masquées"}
QUICK_FEEDBACK = (("favorite", "⭐ Favoris"), ("contacted", "📞 Contactés"))

# (sort, order, libellé du menu, libellé court du bouton)
SORT_OPTIONS = (
    ("score", "desc", "Score — meilleur d’abord", "Score"),
    ("price", "asc", "Prix croissant", "Prix ↑"),
    ("price", "desc", "Prix décroissant", "Prix ↓"),
    ("distance", "asc", "Distance — plus proche d’abord", "Distance"),
    ("created_at", "desc", "Derniers ajouts", "Récentes"),
)


@dataclass
class Link:
    label: str
    url: str
    title: str = ""
    current: bool = False


@dataclass
class FilterBar:
    chips: List[Link] = field(default_factory=list)
    quick: List[Link] = field(default_factory=list)
    sorts: List[Link] = field(default_factory=list)
    sort_label: str = ""
    clear_url: str = "/"

    @property
    def count(self) -> int:
        return len(self.chips)


def url_with(args, **changes: Optional[str]) -> str:
    """URL de la liste avec certains paramètres remplacés (None ou "" : retirés)."""
    params = [(k, v) for k, v in args.items(multi=True)
              if k not in TRANSIENT_PARAMS and k not in changes and v != ""]
    params += [(k, v) for k, v in changes.items() if v not in (None, "")]
    return "/?" + urlencode(params) if params else "/"


def _chips(args, f: ListingFilters) -> List[Link]:
    chips = []

    def chip(label, param, title=""):
        chips.append(Link(label, url_with(args, **{param: None}), title or f"Retirer le filtre « {label} »"))

    if f.prix_min:
        chip(f"Prix ≥ {f.prix_min} €", "prix_min")
    if f.prix_max:
        chip(f"Prix ≤ {f.prix_max} €", "prix_max")
    if f.site:
        chip(f.site, "site")
    if f.status in STATUS_LABELS:
        chip(STATUS_LABELS[f.status], "status")
    if f.dups == "hide":
        chip("Sans doublons", "dups")
    if f.fb == "dislike":
        chip("👎 Pas intéressé", "fb")
    elif f.fb == "any":
        chip("Avec les 👎", "fb")
    if f.excl == "only":
        chip("Exclues seulement", "excl")
    elif f.excl == "show":
        chip("Exclues incluses", "excl")
    return chips


def filter_bar(args, sort: str, order: str) -> FilterBar:
    f = ListingFilters.from_args(args).cleaned()
    sort = "distance" if sort == "distance_enac_km" else sort
    bar = FilterBar(chips=_chips(args, f))
    bar.clear_url = url_with(args, **{name: None for name in FILTER_PARAMS})

    for value, label in QUICK_FEEDBACK:
        on = f.fb == value
        bar.quick.append(Link(label, url_with(args, fb=None if on else value),
                              "Retirer ce filtre" if on else f"Afficher seulement les {label[2:].lower()}", on))

    for s, o, label, short in SORT_OPTIONS:
        current = (s, o) == (sort, order)
        bar.sorts.append(Link(label, url_with(args, sort=s, order=o), current=current))
        if current:
            bar.sort_label = short
    if not bar.sort_label:   # combinaison hors menu (ex. score croissant) : libellé générique
        short = next((sh for s, _, _, sh in SORT_OPTIONS if s == sort), sort)
        bar.sort_label = f"{short.split(' ')[0]} {'↑' if order == 'asc' else '↓'}"
    return bar
