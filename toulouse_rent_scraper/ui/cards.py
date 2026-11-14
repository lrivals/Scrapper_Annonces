# ui/cards.py
# =========================
# Ce qu'affiche la carte d'une annonce dans l'interface, calculé à partir d'une ligne
# de `storage.queries.list_annonces`. Les fiches étant ouvertes pendant le scraping
# (Sprint 16), surface, charges, DPE, annonceur… sont presque toujours connus : la carte
# les regroupe par thème au lieu d'une suite de pastilles identiques.
# =========================

import json
from typing import Dict, List, Optional, Tuple

from utils.formatting import km_label

LEASE_LABELS = {
    "mobilite": "Bail mobilité", "etudiant": "Bail étudiant",
    "colocation": "Colocation", "saisonnier": "Saisonnier",
}
PUBLISHER_LABELS = {"individual": "Particulier", "agency": "Agence"}
ENERGY_CLASSES = "ABCDEFG"

Chip = Tuple[str, str]          # (libellé, infobulle)


def _ddmm(value: Optional[str]) -> Optional[str]:
    """« 2026-11-12… » → « 12/11 »."""
    if not value or len(value) < 10:
        return None
    return f"{value[8:10]}/{value[5:7]}"


def _floor(floor) -> Optional[str]:
    if floor is None:
        return None
    floor = int(floor)
    if floor == 0:
        return "RDC"
    return "1ᵉʳ ét." if floor == 1 else f"{floor}ᵉ ét."


def _photo_count(photos_json) -> int:
    try:
        photos = json.loads(photos_json) if photos_json else []
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(photos) if isinstance(photos, list) else 0


def _energy(a: Dict) -> List[Tuple[str, str]]:
    out = []
    for label, key in (("DPE", "dpe_rating"), ("GES", "ges_rating")):
        grade = (a.get(key) or "").strip().upper()[:1]
        if grade and grade in ENERGY_CLASSES:
            out.append((label, grade))
    return out


def _housing(a: Dict) -> List[Chip]:
    chips = []
    # Meublé : valeur par défaut des cartes de recherche, fiable seulement une fois la fiche lue
    if a.get("furnished") is not None and a.get("enrichment_status") == "done":
        chips.append(("Meublé" if a["furnished"] else "Vide", "Meublé / non meublé"))
    if a.get("elevator"):
        chips.append(("Ascenseur", "Ascenseur"))
    if a.get("deposit"):
        chips.append((f"Dépôt {a['deposit']} €", "Dépôt de garantie"))
    return chips


def _conditions(a: Dict) -> List[Chip]:
    """Conditions de location, surtout tirées de la description par l'analyse LLM (15.4)."""
    chips = []
    available = a.get("available_from")
    if available == "immediate":
        chips.append(("Dispo immédiate", "Disponibilité"))
    elif _ddmm(available):
        chips.append((f"Dispo {_ddmm(available)}", f"Disponible le {available}"))
    if a.get("lease_type") in LEASE_LABELS:
        chips.append((LEASE_LABELS[a["lease_type"]], "Type de bail"))
    elif a.get("colocation"):
        chips.append(("Colocation", "Logement en colocation"))
    for key, name, title in (("apl_ok", "APL", "APL"), ("visale_ok", "Visale", "Garantie Visale")):
        if a.get(key):
            chips.append((f"{name} ✓", f"{title} acceptée(s)"))
        elif a.get(key) is not None and not a[key]:
            chips.append((f"{name} ✗", f"{title} refusée(s)"))
    if a.get("agency_fees"):
        chips.append((f"Frais {a['agency_fees']} €", "Honoraires d’agence à la charge du locataire"))
    return chips


def card_view(a: Dict) -> Dict:
    """Champs d'affichage de la carte (voir ui/templates/index.html)."""
    rooms, bedrooms = a.get("nb_rooms"), a.get("nb_bedrooms")
    key_facts = []
    if rooms:
        key_facts.append(f"T{rooms}")
    if a.get("surface_m2"):
        key_facts.append(f"{round(a['surface_m2'])} m²")     # « 46.73 m² » → « 47 m² »
    # Chambres : seulement si elles apprennent quelque chose (un T2 a d'ordinaire 1 chambre)
    if bedrooms and (not rooms or bedrooms != rooms - 1):
        key_facts.append(f"{bedrooms} ch.")
    floor = _floor(a.get("floor"))
    if floor:
        key_facts.append(floor)

    if a.get("charges_included"):
        price_note = "CC"
    elif a.get("charges"):
        price_note = f"+{a['charges']} € ch."
    else:
        price_note = None

    price, surface = a.get("price"), a.get("surface_m2")
    price_per_m2 = round(price / surface) if price and surface else None

    published = _ddmm(a.get("published_at"))
    seen = _ddmm(a.get("created_at"))
    if published:
        date_label, date_title = f"publiée le {published}", f"Publiée le {a['published_at'][:10]}"
    elif seen:
        date_label, date_title = f"vue le {seen}", "Date de publication inconnue : première détection"
    else:
        date_label, date_title = "Récent", "Date inconnue"

    exact = a.get("geo_precision") == "exact"
    return {
        "key_facts": key_facts,
        "price_note": price_note,
        "price_per_m2": price_per_m2,
        "distance_label": km_label(a.get("distance_km"), a.get("geo_precision")),
        "distance_title": "Position exacte fournie par l’annonce" if exact
                          else "Distance estimée depuis la commune / l’adresse",
        "publisher_label": PUBLISHER_LABELS.get(a.get("publisher_type") or ""),
        "date_label": date_label,
        "date_title": date_title,
        "photo_count": _photo_count(a.get("photos")),
        "energy": _energy(a),
        "chip_groups": [g for g in (_housing(a), _conditions(a)) if g],
        # Un doublon n'est jamais ouvert (Sprint 16 ouvre l'original) : pas de « fiche à lire » pour lui
        "partial": a.get("enrichment_status") == "pending" and not a.get("duplicate_of"),
    }
