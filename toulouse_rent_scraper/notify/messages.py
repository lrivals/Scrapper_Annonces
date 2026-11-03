# notify/messages.py
# =========================
# Construction des messages à partir des événements d'un run :
#   {"kind": "new" | "price_drop", "profile": "enac", "url": ..., "old_price": ...}
# Les infos (titre, prix, distance, score) sont relues en base après le calcul des scores.
# =========================

from collections import defaultdict
from typing import Dict, List

import config
from config import SEARCH_PROFILES


def _line(a: Dict) -> str:
    parts = [f"{a['price']} €"]
    if a.get("distance_km") is not None:
        parts.append(f"{a['distance_km']:.1f} km")
    if a.get("score") is not None:
        parts.append(f"★ {round(a['score'])}")
    return f"{a.get('title') or 'Annonce'} — " + " · ".join(parts)


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
            if (a.get("score") or 0) < config.NOTIFY_MIN_SCORE:
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
            if e["kind"] == "price_drop":
                title = f"Baisse de {e['old_price'] - a['price']} € — {label}"
                body = f"{_line(a)}\n(avant : {e['old_price']} €)"
                tags = ["chart_with_downwards_trend"]
            else:
                title = f"Nouvelle annonce — {label}"
                body = _line(a) + (f"\n{a['location_raw']}" if a.get("location_raw") else "")
                tags = ["house"]
            priority = "high" if (a.get("score") or 0) >= 75 else "default"
            messages.append({"title": title, "body": body, "url": a["url"], "priority": priority, "tags": tags})
    return messages
