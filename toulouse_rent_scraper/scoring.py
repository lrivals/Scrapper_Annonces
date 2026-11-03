# scoring.py
# =========================
# Score d'intérêt 0–100 d'une annonce pour un profil de recherche.
# Chaque critère vaut entre 0 et 1 ; un critère inconnu vaut 0.5 (neutre),
# il ne pénalise ni n'exclut l'annonce.
# =========================

import json
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

from config import DPE_SCORES, SCORE_WEIGHTS, SEARCH_PROFILES, SearchProfile
from utils.logger import setup_logger

logger = setup_logger("scoring")

NEUTRAL = 0.5


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def rent_cc(price: Optional[int], charges: Optional[int]) -> Optional[int]:
    if price is None:
        return None
    return price + (charges or 0)


def rent_score(price: Optional[int], charges: Optional[int], profile: SearchProfile) -> float:
    """1 au loyer cible (ou en dessous), 0 au budget max, linéaire entre les deux."""
    cc = rent_cc(price, charges)
    if cc is None:
        return NEUTRAL
    target = profile.target_rent_eur or profile.min_rent_eur
    if profile.max_rent_eur <= target:
        return 1.0 if cc <= profile.max_rent_eur else 0.0
    return _clamp((profile.max_rent_eur - cc) / (profile.max_rent_eur - target))


def distance_score(distance_km: Optional[float], profile: SearchProfile) -> float:
    """1 sur la cible, 0 en limite de rayon."""
    if distance_km is None:
        return NEUTRAL
    return _clamp(1 - distance_km / profile.max_distance_km)


def price_per_m2(price: Optional[int], surface: Optional[float]) -> Optional[float]:
    if not price or not surface or surface <= 0:
        return None
    return price / surface


def price_per_m2_score(ppm2: Optional[float], median_ppm2: Optional[float]) -> float:
    """1 à la moitié de la médiane ou moins, 0.5 à la médiane, 0 à 1.5× la médiane."""
    if ppm2 is None or not median_ppm2:
        return NEUTRAL
    return _clamp(1.5 - ppm2 / median_ppm2)


def furnished_score(furnished) -> float:
    if furnished is None:
        return NEUTRAL
    return 1.0 if furnished else 0.0


def dpe_score(rating: Optional[str]) -> float:
    if not rating:
        return NEUTRAL
    return DPE_SCORES.get(rating.strip().upper()[:1], NEUTRAL)


_LABELS = {
    "loyer": "Loyer CC",
    "distance": "Distance",
    "prix_m2": "€/m²",
    "meuble": "Meublé",
    "dpe": "DPE",
}


def compute_score(
    annonce: Dict,
    distance_km: Optional[float],
    profile: SearchProfile,
    median_ppm2: Optional[float] = None,
    weights: Dict[str, float] = SCORE_WEIGHTS,
) -> Tuple[float, Dict[str, float]]:
    """Retourne (score sur 100, valeur 0–1 de chaque critère)."""
    detail = {
        "loyer": rent_score(annonce.get("price"), annonce.get("charges"), profile),
        "distance": distance_score(distance_km, profile),
        "prix_m2": price_per_m2_score(
            price_per_m2(annonce.get("price"), annonce.get("surface_m2")), median_ppm2
        ),
        "meuble": furnished_score(annonce.get("furnished")),
        "dpe": dpe_score(annonce.get("dpe_rating")),
    }
    total_weight = sum(weights.get(k, 0) for k in detail)
    if not total_weight:
        return 0.0, detail
    score = sum(detail[k] * weights.get(k, 0) for k in detail) / total_weight * 100
    return round(score, 1), {k: round(v, 2) for k, v in detail.items()}


def describe(detail_json: Optional[str]) -> str:
    """Texte du survol UI : « Loyer CC 0.8 · Distance 0.6 … »."""
    if not detail_json:
        return ""
    try:
        detail = json.loads(detail_json)
    except (TypeError, ValueError):
        return ""
    return " · ".join(f"{_LABELS.get(k, k)} {round(v * 10)}/10" for k, v in detail.items())


def median_price_per_m2(rows: Iterable[Dict]) -> Optional[float]:
    values = [
        v for v in (price_per_m2(r.get("price"), r.get("surface_m2")) for r in rows)
        if v is not None
    ]
    return median(values) if values else None


def rescore(profile_keys: Optional[List[str]] = None) -> int:
    """
    Recalcule le score de toutes les annonces des profils donnés (défaut : tous).
    La médiane €/m² est prise sur les annonces actives du profil. Retourne le nombre d'annonces notées.
    """
    from storage.sqlite import annonces_for_scoring, save_scores

    count = 0
    for key in profile_keys or list(SEARCH_PROFILES):
        profile = SEARCH_PROFILES[key]
        rows = annonces_for_scoring(key)
        med = median_price_per_m2(r for r in rows if (r.get("status") or "active") == "active")
        updates = []
        for row in rows:
            score, detail = compute_score(row, row.get("distance_km"), profile, med)
            updates.append((row["id"], score, json.dumps(detail)))
        save_scores(key, updates)
        count += len(updates)
        logger.debug(f"Scores recalculés : {len(updates)} annonces ({profile.label})")
    return count
