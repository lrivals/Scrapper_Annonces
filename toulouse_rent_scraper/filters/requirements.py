# filters/requirements.py
# =========================
# Sprint 15.5 — critères éliminatoires par profil.
# Une annonce est exclue d'un profil si une information CONNUE viole un critère ;
# une information absente (non extraite, non analysée) la laisse passer.
# =========================

from datetime import date
from typing import Dict, List, Optional

from config import Requirements

LEASE_LABELS = {
    "classique": "bail classique", "meuble": "bail meublé", "mobilite": "bail mobilité",
    "etudiant": "bail étudiant", "colocation": "colocation", "saisonnier": "location saisonnière",
}
DPE_ORDER = "ABCDEFG"


def _iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _fr(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def exclusion_reasons(annonce: Dict, req: Requirements) -> List[str]:
    """Raisons (lisibles) pour lesquelles l'annonce viole les critères ; [] = conservée."""
    if req.is_empty():
        return []
    reasons = []

    deadline = _iso(req.available_before)
    available = annonce.get("available_from")
    if deadline and available and available != "immediate":
        when = _iso(available)
        if when and when > deadline:
            reasons.append(f"disponible le {_fr(when)} (après le {_fr(deadline)})")

    if req.apl_required and annonce.get("apl_ok") is not None and not annonce["apl_ok"]:
        reasons.append("APL refusées")

    floor = annonce.get("floor")
    if req.no_ground_floor and floor is not None and int(floor) == 0:
        reasons.append("rez-de-chaussée")

    surface = annonce.get("surface_m2")
    if req.min_surface_m2 and surface and surface < req.min_surface_m2:
        reasons.append(f"{surface:g} m² (minimum {req.min_surface_m2:g} m²)")

    furnished = annonce.get("furnished")
    # Meublé non fiable tant que l'annonce n'est pas enrichie (valeur par défaut des cartes)
    known = annonce.get("enrichment_status") in (None, "done")
    if req.furnished is not None and furnished is not None and known and bool(furnished) != req.furnished:
        reasons.append("meublé" if furnished else "non meublé")

    lease = annonce.get("lease_type")
    if req.no_colocation and (annonce.get("colocation") or lease == "colocation"):
        reasons.append("colocation")
    if lease and lease in req.excluded_lease_types and not (req.no_colocation and lease == "colocation"):
        reasons.append(LEASE_LABELS.get(lease, lease))

    dpe = (annonce.get("dpe_rating") or "").strip().upper()[:1]
    if req.max_dpe and dpe in DPE_ORDER and DPE_ORDER.index(dpe) > DPE_ORDER.index(req.max_dpe.upper()):
        reasons.append(f"DPE {dpe} (maximum {req.max_dpe.upper()})")

    return reasons


def describe_requirements(req: Requirements) -> List[str]:
    """Critères du profil en clair (infobulle de l'UI, résumé CLI)."""
    items = []
    if req.available_before and _iso(req.available_before):
        items.append(f"libre avant le {_fr(_iso(req.available_before))}")
    if req.apl_required:
        items.append("APL acceptées")
    if req.no_ground_floor:
        items.append("pas de rez-de-chaussée")
    if req.min_surface_m2:
        items.append(f"≥ {req.min_surface_m2:g} m²")
    if req.furnished is not None:
        items.append("meublé" if req.furnished else "non meublé")
    if req.no_colocation:
        items.append("pas de colocation")
    for lease in req.excluded_lease_types:
        items.append(f"pas de {LEASE_LABELS.get(lease, lease)}")
    if req.max_dpe:
        items.append(f"DPE {req.max_dpe.upper()} ou mieux")
    return items
