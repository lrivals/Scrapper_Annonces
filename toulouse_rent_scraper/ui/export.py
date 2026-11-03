# ui/export.py
# =========================
# Export Markdown du « dossier de candidature » (annonces sélectionnées)
# =========================

from datetime import datetime
from typing import Dict, List, Optional

from config import SearchProfile


def build_candidature_markdown(
    annonces: List[Dict], profile: SearchProfile, now: Optional[datetime] = None
) -> str:
    """Dossier Markdown : une section par annonce, avec notes, critères et suivi."""
    today = (now or datetime.now()).strftime("%d/%m/%Y")
    lines = [
        f"# Dossier de candidature — {profile.label} — {today}",
        "",
        f"_{len(annonces)} annonce{'s' if len(annonces) > 1 else ''} sélectionnée{'s' if len(annonces) > 1 else ''}_",
        "",
        "---",
        "",
    ]

    for i, a in enumerate(annonces, 1):
        title = a.get("title") or f"Annonce #{a['id']}"
        url = a.get("url") or ""
        price = f"{a['price']} €/mois" if a.get("price") else "—"
        surface = f"{a['surface_m2']} m²" if a.get("surface_m2") else "—"
        rooms = str(a["nb_rooms"]) if a.get("nb_rooms") else "—"
        location = a.get("location_raw") or "Toulouse"
        dist = f"{a['distance_km']:.1f} km" if a.get("distance_km") is not None else "—"
        site = a.get("site") or "—"
        status = {"active": "En ligne", "expired": "Expiré", "hidden": "Masquée"}.get(a.get("status") or "active", "—")
        created = (a.get("created_at") or "")[:10] or "—"
        furnished = ("Oui" if a.get("furnished") else "Non") if a.get("furnished") is not None else "—"
        charges = f"{a['charges']} €" if a.get("charges") else "—"
        deposit = f"{a['deposit']} €" if a.get("deposit") else "—"

        lines += [
            f"## {i}. [{title}]({url})",
            "",
            f"**Plateforme :** {site}  ",
            f"**Prix :** {price}  ",
            f"**Surface :** {surface}  ",
            f"**Pièces :** {rooms}  ",
            f"**Localisation :** {location}  ",
            f"**Distance {profile.label} :** {dist}  ",
            f"**Meublé :** {furnished}  ",
            f"**Charges :** {charges}  ",
            f"**Dépôt de garantie :** {deposit}  ",
            f"**Statut :** {status}  ",
            f"**Ajoutée le :** {created}  ",
            "",
            "### Notes personnelles",
            "",
            "",
            "",
            "### Critères",
            "",
            "- [ ] Loyer dans le budget",
            f"- [ ] Distance {profile.label} acceptable",
            "- [ ] Meublé / équipements OK",
            "- [ ] Disponibilité confirmée",
            "",
            "### Suivi candidature",
            "",
            "| Étape | Date | Notes |",
            "|-------|------|-------|",
            "| Premier contact | | |",
            "| Visite | | |",
            "| Dépôt dossier | | |",
            "| Réponse | | |",
            "| Décision | | |",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def candidature_filename(profile: SearchProfile, now: Optional[datetime] = None) -> str:
    return f"candidatures_{profile.key}_{(now or datetime.now()):%Y%m%d}.md"
