# ui/details.py
# =========================
# Panneau « Détails » d'une carte dépliée (vue liste) : photos, description complète,
# particularités lues sur la fiche (`extra_attributes`, brut par site), détail du score,
# historique des prix. Les clés techniques des sites (identifiants, logos, options de
# visibilité…) ne sont jamais affichées : seules les clés listées ici le sont.
# =========================

import json
from typing import Dict, List, Optional, Tuple

from scoring import LABELS as SCORE_LABELS

GROUPS = ("Logement", "Extérieurs & stationnement", "Chauffage & énergie", "Frais & conditions")
LOGEMENT, EXTERIEUR, ENERGIE, FRAIS = GROUPS

# clé brute → (groupe, libellé). Libellé None : la valeur se suffit (« Cuisine intégrée »).
LEBONCOIN = {
    "specificities": (LOGEMENT, "Particularités"),
    "nb_bathrooms": (LOGEMENT, "Salles de bain"),
    "nb_shower_room": (LOGEMENT, "Salles d'eau"),
    "global_condition": (LOGEMENT, "État"),
    "building_year": (LOGEMENT, "Construction"),
    "nb_floors_building": (LOGEMENT, "Étages de l'immeuble"),
    "outside_access": (EXTERIEUR, "Extérieur"),
    "nb_parkings": (EXTERIEUR, "Places de parking"),
    "orientation": (EXTERIEUR, "Orientation"),
    "heating_mode": (ENERGIE, "Chauffage"),
    "heating_type": (ENERGIE, "Type de chauffage"),
    "rent_excluding_charges": (FRAIS, "Loyer hors charges"),
    "real_estate_charges_details": (FRAIS, "Charges comprenant"),
    "inventory_fees": (FRAIS, "État des lieux"),
    "is_public_rent_control": (FRAIS, "Loyer encadré"),
}
SELOGER = {
    "livingRoom": (LOGEMENT, None),
    "kitchen": (LOGEMENT, None),
    "bathroom-amenities": (LOGEMENT, None),
    "toilet-amenities": (LOGEMENT, None),
    "separateEntrance": (LOGEMENT, None),
    "floor-covering": (LOGEMENT, None),
    "État": (LOGEMENT, "État"),
    "Année de construction": (LOGEMENT, "Construction"),
    "intercom": (LOGEMENT, None),
    "digital-lock": (LOGEMENT, None),
    "barrier-free": (LOGEMENT, None),
    "calm": (LOGEMENT, None),
    "district": (LOGEMENT, "Quartier"),
    "balcony": (EXTERIEUR, None),
    "terrace": (EXTERIEUR, None),
    "garden": (EXTERIEUR, None),
    "swimming-pool": (EXTERIEUR, None),
    "parking-lots": (EXTERIEUR, None),
    "cellar": (EXTERIEUR, None),
    "Orientation": (EXTERIEUR, None),
    "with-view": (EXTERIEUR, None),
    "Type de chauffage": (ENERGIE, "Chauffage"),
    "Sources d'énergie": (ENERGIE, "Énergie"),
}
BIENICI_FLAGS = (   # booléen, quantité éventuelle, singulier, pluriel, groupe
    ("hasBalcony", "balconyQuantity", "Balcon", "balcons", EXTERIEUR),
    ("hasTerrace", "terracesQuantity", "Terrasse", "terrasses", EXTERIEUR),
    ("hasGarden", None, "Jardin", None, EXTERIEUR),
    ("hasCellar", None, "Cave", None, EXTERIEUR),
    ("hasPool", None, "Piscine", None, EXTERIEUR),
    ("isDisabledPeopleFriendly", None, "Accessible PMR", None, LOGEMENT),
)

# Valeurs qui disent « absent » : rien à montrer (« Sans vis-à-vis » est un atout, gardé)
NEGATIVE_PREFIXES = ("pas ", "pas d'", "non ", "aucun")
NEGATIVE_VALUES = {"non", "vierge", "false", "0", ""}


def _is_negative(value: str) -> bool:
    low = value.strip().lower()
    return low in NEGATIVE_VALUES or low.startswith(NEGATIVE_PREFIXES)


def _clean(value) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    if _is_negative(text):
        return None
    # « Non accessible, Non accessible aux personnes… » : garder les parties positives seulement
    # séparateur « , » + espace : « 6,2 m² » (virgule décimale) reste entier
    parts = [p.strip() for p in text.split(", ") if p.strip() and not _is_negative(p)]
    return ", ".join(parts) or None


def _attributes(site: str, extra: Dict) -> Dict[str, List[Tuple[Optional[str], str]]]:
    groups: Dict[str, List[Tuple[Optional[str], str]]] = {g: [] for g in GROUPS}
    site_l = (site or "").lower()
    if "bien" in site_l:
        for flag, qty_key, single, plural, group in BIENICI_FLAGS:
            if extra.get(flag) is True or str(extra.get(flag)) == "1":
                qty = extra.get(qty_key) if qty_key else None
                label = f"{qty} {plural}" if plural and isinstance(qty, int) and qty > 1 else single
                groups[group].append((None, label))
        if isinstance(extra.get("parkingPlacesQuantity"), int) and extra["parkingPlacesQuantity"] > 0:
            groups[EXTERIEUR].append(("Places de parking", str(extra["parkingPlacesQuantity"])))
        heating = _clean(extra.get("heating"))
        if heating:
            groups[ENERGIE].append(("Chauffage", heating))
        return groups

    if site_l == "pap":
        street, city = _clean(extra.get("street")), _clean(extra.get("city"))
        if street:
            groups[LOGEMENT].append(("Adresse", f"{street}, {city}" if city else street))
        if extra.get("balcony_or_terrace") is True:
            groups[EXTERIEUR].append((None, "Balcon / terrasse"))
        return groups

    table = LEBONCOIN if "leboncoin" in site_l else SELOGER if "seloger" in site_l else {}
    for key, (group, label) in table.items():
        if key == "is_public_rent_control":
            if str(extra.get(key, "")).lower() == "oui":
                groups[group].append((None, "Loyer encadré"))
            continue
        value = _clean(extra.get(key))
        if not value:
            continue
        if key == "rent_excluding_charges" and value.isdigit():
            value = f"{value} €"
        groups[group].append((label, value))

    # Budget énergie annuel (LBC) : une seule ligne « 920 – 990 € / an »
    low, high = _clean(extra.get("annual_energy_budget_min")), _clean(extra.get("annual_energy_budget_max"))
    if low and high:
        groups[ENERGIE].append(("Budget énergie", f"{low.replace(' €', '')} – {high} / an"))
    return groups


def _money(value) -> Optional[str]:
    try:
        return f"{round(float(value))} €" if value not in (None, "") and float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def _base_conditions(a: Dict, extra: Dict) -> List[Tuple[Optional[str], str]]:
    """Charges, honoraires, disponibilité : colonnes de la base (déjà normalisées par site)."""
    rows = []
    if a.get("charges"):
        rows.append(("Charges", f"{a['charges']} € / mois" + (" (comprises)" if a.get("charges_included") else "")))
    fees = _money(a.get("agency_fees")) or _money(extra.get("agencyRentalFee")) \
        or _money(extra.get("honoraires")) or _money(extra.get("rental_fees"))
    if fees:
        rows.append(("Honoraires", fees))
    available = a.get("available_from")
    if available == "immediate":
        rows.append(("Disponibilité", "immédiate"))
    elif available and len(available) >= 10:
        rows.append(("Disponibilité", f"{available[8:10]}/{available[5:7]}/{available[:4]}"))
    else:
        raw = _clean(extra.get("availability") or extra.get("available_date"))
        if raw:
            rows.append(("Disponibilité", raw))
    return rows


def _json(value, default):
    try:
        out = json.loads(value) if value else default
    except (TypeError, ValueError):
        return default
    return out if isinstance(out, type(default)) else default


def detail_view(a: Dict, price_history: List[Dict]) -> Dict:
    extra = _json(a.get("extra_attributes"), {})
    groups = _attributes(a.get("site", ""), extra)
    groups[FRAIS] = _base_conditions(a, extra) + groups[FRAIS]

    detail = _json(a.get("score_detail"), {})
    score_bars = [(SCORE_LABELS.get(k, k), round(float(v) * 10))
                  for k, v in detail.items() if isinstance(v, (int, float))]

    history = [h for h in price_history if h.get("price")]
    enriched = a.get("enriched_at") or ""
    meta = []
    if extra.get("store_name"):
        meta.append(("Annonceur", str(extra["store_name"])))
    reference = extra.get("custom_ref") or extra.get("reference")
    if reference:
        meta.append(("Référence", str(reference)))
    if a.get("enrichment_status") == "done" and enriched:
        meta.append(("Fiche lue le", f"{enriched[8:10]}/{enriched[5:7]}/{enriched[:4]}"))
    if extra.get("virtual_tour"):
        meta.append(("Visite virtuelle", str(extra["virtual_tour"])))

    return {
        "photos": [p for p in _json(a.get("photos"), []) if isinstance(p, str)],
        "description": (a.get("description") or "").strip(),
        "groups": [(name, rows) for name, rows in groups.items() if rows],
        "score_bars": score_bars,
        "price_history": history if len(history) >= 2 else [],
        "summary": a.get("summary"),
        "scam_flags": _json(a.get("scam_flags"), []),
        "meta": meta,
        "pending": a.get("enrichment_status") == "pending",
    }
