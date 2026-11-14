# notify/messages.py
# =========================
# Construction des messages à partir des événements d'un run :
#   {"kind": "new" | "price_drop", "profile": "enac", "url": ..., "old_price": ...}
# Les infos (titre, prix, distance, score) sont relues en base après le calcul des scores.
# =========================

from collections import defaultdict
from typing import Dict, List, Optional

import config
from config import SEARCH_PROFILES
from utils.formatting import km_label


def _line(a: Dict) -> str:
    """
    « Titre — T2 · 38 m² · 690 € (+40 € ch.) · DPE C · 5,2 km · ★ 80 » ; champs absents omis.
    Sprint 16 : les fiches sont ouvertes avant l'envoi, surface / charges / DPE sont connus.
    « ≈ » devant une distance calculée depuis la commune (pas le point GPS de l'annonce).
    """
    parts = []
    if a.get("nb_rooms"):
        parts.append(f"T{a['nb_rooms']}")
    if a.get("surface_m2"):
        parts.append(f"{a['surface_m2']:g} m²")
    price = f"{a['price']} €"
    if a.get("charges_included"):
        price += " CC"
    elif a.get("charges"):
        price += f" (+{a['charges']} € ch.)"
    parts.append(price)
    if a.get("dpe_rating"):
        parts.append(f"DPE {a['dpe_rating']}")
    distance = km_label(a.get("distance_km"), a.get("geo_precision"))
    if distance:
        parts.append(distance)
    if a.get("score") is not None:
        parts.append(f"★ {round(a['score'])}")
    # Analyse LLM (15.4)
    if a.get("available_from"):
        parts.append("dispo immédiate" if a["available_from"] == "immediate"
                     else f"dispo {a['available_from'][8:10]}/{a['available_from'][5:7]}")
    prefix = "⚠️ " if a.get("scam_risk") == "eleve" else ""
    return f"{prefix}{a.get('title') or 'Annonce'} — " + " · ".join(parts)


def build_messages(events: List[Dict]) -> List[Dict]:
    """Liste de kwargs pour notify.send(), filtrés par score et regroupés par profil."""
    from storage.sqlite import annonces_for_notification

    by_profile = defaultdict(list)
    for e in events:
        by_profile[e["profile"]].append(e)

    messages = []
    for key, profile_events in by_profile.items():
        label = SEARCH_PROFILES[key].label if key in SEARCH_PROFILES else key
        infos = annonces_for_notification(key, [e["url"] for e in profile_events])

        items = []
        seen = set()
        for e in profile_events:
            a = infos.get(e["url"])
            if not a or e["url"] in seen:
                continue
            # Même bien déjà connu sur un autre site (doublon) : pas une nouveauté
            if e["kind"] == "new" and a.get("duplicate_of"):
                continue
            # Un favori (⭐, 15.6) est toujours suivi, quel que soit son score
            if (a.get("score") or 0) < config.NOTIFY_MIN_SCORE and a.get("feedback") != "favorite":
                continue
            seen.add(e["url"])
            items.append((e, a))
        if not items:
            continue
        items.sort(key=lambda ea: ea[1].get("score") or 0, reverse=True)

        if len(items) > config.NOTIFY_GROUP_THRESHOLD:
            shown = items[: config.NOTIFY_GROUP_MAX_ITEMS]
            body = "\n".join(f"• {_line(a)}" for _, a in shown)
            if len(items) > len(shown):
                body += f"\n… et {len(items) - len(shown)} autre(s) dans l'interface"
            messages.append({
                "title": f"{len(items)} annonces intéressantes — {label}",
                "body": body,
                "url": shown[0][1]["url"],
                "priority": "default",
                "tags": ["house"],
            })
            continue

        for e, a in items:
            favorite = a.get("feedback") == "favorite"
            if e["kind"] == "price_drop":
                title = f"{'⭐ ' if favorite else ''}Baisse de {e['old_price'] - a['price']} € — {label}"
                body = f"{_line(a)}\n(avant : {e['old_price']} €)"
                tags = ["chart_with_downwards_trend"]
            else:
                title = f"Nouvelle annonce — {label}"
                body = _line(a) + (f"\n{a['location_raw']}" if a.get("location_raw") else "")
                tags = ["house"]
            priority = "high" if (a.get("score") or 0) >= 75 or favorite else "default"
            messages.append({"title": title, "body": body, "url": a["url"], "priority": priority, "tags": tags})
    return messages


def favorite_gone_messages(annonces: List[Dict]) -> List[Dict]:
    """
    Sprint 15.6 — favoris (⭐) devenus indisponibles. `annonces` : dicts avec id, title,
    price, url. Un message par annonce, avec les profils où elle était en favori.
    """
    from storage.feedback import favorites_by_annonce

    favorites = favorites_by_annonce([a["id"] for a in annonces])
    messages = []
    for a in annonces:
        profiles = favorites.get(a["id"])
        if not profiles:
            continue
        labels = ", ".join(SEARCH_PROFILES[p].label if p in SEARCH_PROFILES else p for p in profiles)
        price = f"{a['price']} € — " if a.get("price") else ""
        messages.append({
            "title": f"⭐ Favori retiré — {labels}",
            "body": f"{price}{a.get('title') or 'Annonce'}\nL'annonce n'est plus disponible sur le site.",
            "url": a["url"],
            "priority": "high",
            "tags": ["wastebasket"],
        })
    return messages


TELEGRAM_MAX_CHARS = 4096


def top10_message(profile_key: str, ads: List[Dict], n: int = 10) -> Optional[Dict]:
    """
    Sprint 5.6 — Top 10 d'un profil en un message : une ligne par annonce et son lien
    (texte brut, lisible sur Telegram comme sur ntfy). None si aucune annonce.
    """
    from reporting.generator import _by_score, market_line, _new_today, top10_lines

    best = _by_score(ads)[:n]
    if not best:
        return None
    label = SEARCH_PROFILES[profile_key].label if profile_key in SEARCH_PROFILES else profile_key
    lines = []
    for line, ad in zip(top10_lines(best, n=n), best):
        # « 1. ⭐ 92 | … | [lien](url) » → texte brut, lien sur sa propre ligne
        text = line.rsplit(" | [lien](", 1)[0].replace(" | ", " · ")
        lines.append(f"{text}\n{ad['url']}")
    body = "\n".join(lines) + "\n\n" + market_line(ads, _new_today(ads))
    # Marge pour le titre ajouté par le backend
    limit = TELEGRAM_MAX_CHARS - 200
    if len(body) > limit:
        body = body[:limit].rsplit("\n", 1)[0] + "\n…"
    return {"title": f"🏆 Top {len(best)} — {label}", "body": body, "priority": "low", "tags": ["trophy"]}
