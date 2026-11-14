# utils/formatting.py
# =========================
# Petits formats partagés entre l'interface et les notifications.
# =========================

from typing import Optional


def km_label(distance_km: Optional[float], geo_precision: Optional[str] = None) -> Optional[str]:
    """
    « 5,2 km », précédé de « ≈ » quand la distance vient du géocodage de la commune
    (pas du point GPS de l'annonce). None si la distance est inconnue.
    """
    if distance_km is None:
        return None
    approx = "" if geo_precision == "exact" else "≈ "
    return approx + f"{float(distance_km):.1f}".replace(".", ",") + " km"
