# filters/requirements.py
# =========================
# Sprint 15.5 — critères éliminatoires par profil.
# Une annonce est exclue d'un profil si une information CONNUE viole un critère ;
# une information absente (non extraite, non analysée) la laisse passer.
# =========================

import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Dict, List, Mapping, Optional, Tuple

import config
from config import Requirements
from utils.logger import setup_logger

logger = setup_logger("requirements")

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


# ---------------------------------------------------------------------------
# Critères effectifs : saisis dans l'interface (fichier), sinon ceux de config.py
# ---------------------------------------------------------------------------

def _read_file() -> Dict:
    try:
        data = json.loads(config.REQUIREMENTS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"Critères illisibles ({config.REQUIREMENTS_FILE.name}) : {e} — config.py utilisé")
        return {}
    return data if isinstance(data, dict) else {}


def requirements_from_dict(data: Mapping) -> Requirements:
    """Dict (fichier JSON) → Requirements ; une valeur invalide est ignorée, jamais d'exception."""
    req, _ = parse_requirements({
        "available_before": data.get("available_before") or "",
        "min_surface_m2": "" if data.get("min_surface_m2") is None else str(data.get("min_surface_m2")),
        "furnished": {True: "yes", False: "no"}.get(data.get("furnished"), ""),
        "max_dpe": data.get("max_dpe") or "",
        "excluded_lease_types": list(data.get("excluded_lease_types") or []),
        **{k: "on" for k in ("apl_required", "no_ground_floor", "no_colocation") if data.get(k)},
    })
    return req


def current_requirements(profile) -> Requirements:
    """Critères du profil : ceux de l'interface s'ils existent, sinon `profile.requirements`."""
    entry = _read_file().get(profile.key)
    if isinstance(entry, dict) and isinstance(entry.get("requirements"), dict):
        return requirements_from_dict(entry["requirements"])
    return profile.requirements


def requirements_source(profile) -> str:
    entry = _read_file().get(profile.key)
    return "interface" if isinstance(entry, dict) and "requirements" in entry else "config.py"


def save_requirements(profile_key: str, req: Requirements) -> None:
    data = _read_file()
    values = asdict(req)
    values["excluded_lease_types"] = list(req.excluded_lease_types)
    data[profile_key] = {"requirements": values, "saved_at": datetime.now().isoformat(timespec="seconds")}
    path = config.REQUIREMENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    logger.info(f"Critères du profil {profile_key} enregistrés : {describe_requirements(req) or 'aucun'}")


def reset_requirements(profile_key: str) -> bool:
    """Revient aux critères de config.py pour ce profil. True s'il y en avait dans l'interface."""
    data = _read_file()
    if profile_key not in data:
        return False
    del data[profile_key]
    if data:
        config.REQUIREMENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        config.REQUIREMENTS_FILE.unlink(missing_ok=True)
    logger.info(f"Critères du profil {profile_key} : retour à config.py")
    return True


# Types de bail proposés à l'exclusion (la colocation a sa propre case)
EXCLUDABLE_LEASES = tuple(k for k in LEASE_LABELS if k != "colocation")


def parse_requirements(form) -> Tuple[Requirements, List[str]]:
    """
    Formulaire de l'interface → (Requirements, erreurs lisibles).
    Un champ invalide est signalé et laissé vide ; les autres sont gardés.
    `form` : dict de chaînes (listes pour excluded_lease_types) ou MultiDict Flask.
    """
    errors: List[str] = []

    def get(name: str) -> str:
        value = form.get(name)
        return value.strip() if isinstance(value, str) else ""

    def getlist(name: str) -> List[str]:
        if hasattr(form, "getlist"):
            return form.getlist(name)
        value = form.get(name)
        return list(value) if isinstance(value, (list, tuple)) else []

    available_before = get("available_before") or None
    if available_before and _iso(available_before) is None:
        errors.append(f"date « {available_before} » invalide (AAAA-MM-JJ)")
        available_before = None
    elif available_before:
        available_before = _iso(available_before).isoformat()

    min_surface = None
    if get("min_surface_m2"):
        try:
            min_surface = float(get("min_surface_m2").replace(",", "."))
        except ValueError:
            min_surface = -1
        if not 0 < min_surface < 1000:
            errors.append(f"surface minimale « {get('min_surface_m2')} » invalide")
            min_surface = None

    furnished = {"yes": True, "no": False}.get(get("furnished"))

    max_dpe = get("max_dpe").upper() or None
    if max_dpe and (len(max_dpe) != 1 or max_dpe not in DPE_ORDER):
        errors.append(f"DPE « {max_dpe} » invalide (A à G)")
        max_dpe = None
    if max_dpe == "G":   # « G ou mieux » n'exclut rien
        max_dpe = None

    leases = []
    for lease in getlist("excluded_lease_types"):
        if lease in EXCLUDABLE_LEASES and lease not in leases:
            leases.append(lease)
        elif lease not in EXCLUDABLE_LEASES:
            errors.append(f"type de bail « {lease} » inconnu")

    checked = lambda name: get(name) in ("on", "1", "true", "yes")   # noqa: E731
    req = Requirements(
        available_before=available_before,
        apl_required=checked("apl_required"),
        no_ground_floor=checked("no_ground_floor"),
        min_surface_m2=min_surface,
        furnished=furnished,
        no_colocation=checked("no_colocation"),
        excluded_lease_types=tuple(leases),
        max_dpe=max_dpe,
    )
    return req, errors
