# ui/api.py
# =========================
# Sprint 2-bis.1 — API JSON en lecture seule, montée sur /api/v1 dans l'UI Flask.
#
#   GET /api/v1/profiles                       profils de recherche
#   GET /api/v1/annonces?profile=blagnac&…     annonces (mêmes filtres et tris que la liste de l'UI)
#   GET /api/v1/annonces/<id>?profile=…        une annonce + historique des prix
#   GET /api/v1/runs?profile=…&limit=20        journal des runs (Sprint 5.0)
#   GET /api/v1/stats?profile=…                stock actuel (par site, médianes, nouvelles)
#   GET /api/v1/stats/history?profile=…&days=90  séries par jour et par run (tendances)
#
# Accès : libre depuis la machine (127.0.0.1 / ::1). Depuis une autre adresse (réseau,
# conteneur Docker), jeton API_TOKEN du .env obligatoire :
#   Authorization: Bearer <jeton>   (ou en-tête X-API-Token)
# Sans API_TOKEN configuré, l'API refuse toute requête qui ne vient pas de la machine.
# Lecture seule : aucune route ne modifie la base (pas de CSRF nécessaire).
# =========================

import hmac
import json
from typing import Dict, Optional

from flask import Blueprint, jsonify, request

import config
from config import DEFAULT_PROFILE, SEARCH_PROFILES
from storage.queries import SORT_COLUMNS, ListingFilters, annonce_detail, list_annonces

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
MAX_LIMIT = 500
DEFAULT_LIMIT = 100

# Champs publiés (liste blanche : les colonnes internes — empreintes, erreurs, données
# LLM brutes — restent privées et le format de l'API ne change pas avec le schéma)
LIST_FIELDS = (
    "id", "site", "title", "url", "price", "charges", "charges_included", "location_raw",
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "furnished", "dpe_rating", "ges_rating",
    "publisher_type", "status", "created_at", "published_at", "lat", "lon", "geo_precision",
    "distance_km", "score", "excluded_reasons", "feedback", "duplicate_of", "first_price",
)
DETAIL_FIELDS = LIST_FIELDS + (
    "description", "deposit", "photos", "elevator", "extra_attributes", "score_detail",
    "enrichment_status", "enriched_at", "checked_at", "expired_at",
    "summary", "available_from", "lease_type", "colocation", "apl_ok", "visale_ok", "agency_fees",
    "scam_risk", "scam_flags",
)
JSON_FIELDS = {"photos", "extra_attributes", "score_detail", "excluded_reasons", "scam_flags"}
BOOL_FIELDS = {"charges_included", "furnished", "elevator", "colocation", "apl_ok", "visale_ok"}


def _error(status: int, message: str):
    response = jsonify({"error": message})
    response.status_code = status
    return response


@api_bp.before_request
def _check_access():
    token = config.API_TOKEN
    sent = request.headers.get("X-API-Token") or ""
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        sent = auth[7:].strip()
    if token and sent and hmac.compare_digest(token, sent):
        return None
    if request.remote_addr in LOOPBACK and not sent:
        return None
    if not token:
        return _error(403, "API réservée à la machine locale : définir API_TOKEN dans .env pour un accès distant")
    return _error(401, "Jeton manquant ou invalide (Authorization: Bearer <API_TOKEN>)")


def _profile():
    """Profil demandé (défaut : DEFAULT_PROFILE) ; None si la clé est inconnue."""
    return SEARCH_PROFILES.get(request.args.get("profile") or DEFAULT_PROFILE)


def _unknown_profile():
    return _error(404, f"Profil inconnu : {request.args.get('profile')!r} "
                       f"(connus : {', '.join(SEARCH_PROFILES)})")


def _int_arg(name: str, default: int, minimum: int = 0, maximum: Optional[int] = None) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


def serialize(row: Dict, fields=LIST_FIELDS) -> Dict:
    """Annonce → dict JSON : colonnes JSON décodées, booléens SQLite convertis."""
    out = {}
    for key in fields:
        if key not in row:
            continue
        value = row[key]
        if key in JSON_FIELDS and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        elif key in BOOL_FIELDS and value is not None:
            value = bool(value)
        out[key] = value
    return out


def _profile_dict(p) -> Dict:
    return {
        "key": p.key, "label": p.label, "enabled": p.enabled,
        "target": {"address": p.target_address, "lat": p.target_lat, "lon": p.target_lon},
        "max_distance_km": p.max_distance_km,
        "rent": {"min": p.min_rent_eur, "max": p.max_rent_eur, "target": p.target_rent_eur},
        "rooms": list(p.rooms) if p.rooms else None,
    }


@api_bp.route("/profiles")
def profiles():
    return jsonify({"default": DEFAULT_PROFILE, "items": [_profile_dict(p) for p in SEARCH_PROFILES.values()]})


@api_bp.route("/annonces")
def annonces():
    profile = _profile()
    if profile is None:
        return _unknown_profile()
    sort = request.args.get("sort", "score")
    if sort not in SORT_COLUMNS:
        return _error(400, f"Tri inconnu : {sort!r} (possibles : {', '.join(sorted(SORT_COLUMNS))})")
    order = request.args.get("order") or ("desc" if sort == "score" else "asc")
    if order not in ("asc", "desc"):
        return _error(400, "order : asc ou desc")
    limit = _int_arg("limit", DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT)
    offset = _int_arg("offset", 0)

    filters = ListingFilters.from_args(request.args).cleaned()
    rows = list_annonces(profile.key, filters, sort, order)
    return jsonify({
        "profile": profile.key,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": [serialize(r) for r in rows[offset:offset + limit]],
    })


@api_bp.route("/annonces/<int:annonce_id>")
def annonce(annonce_id: int):
    from storage.sqlite import get_price_history

    profile = _profile()
    if profile is None:
        return _unknown_profile()
    row = annonce_detail(annonce_id, profile.key)
    if row is None:
        return _error(404, f"Annonce {annonce_id} absente du profil {profile.key}")
    data = serialize(row, DETAIL_FIELDS)
    data["price_history"] = get_price_history(annonce_id)
    return jsonify({"profile": profile.key, "item": data})


@api_bp.route("/runs")
def runs():
    from storage.run_stats import last_runs

    profile = _profile()
    if profile is None:
        return _unknown_profile()
    limit = _int_arg("limit", 20, minimum=1, maximum=MAX_LIMIT)
    return jsonify({"profile": profile.key, "items": last_runs(profile.key, limit)})


@api_bp.route("/stats")
def stats():
    from storage.run_stats import last_runs
    from storage.trends import profile_summary

    profile = _profile()
    if profile is None:
        return _unknown_profile()
    latest = last_runs(profile.key, 1)
    return jsonify({
        "profile": profile.key,
        **profile_summary(profile.key),
        "last_run": latest[0] if latest else None,
    })


@api_bp.route("/stats/history")
def stats_history():
    from storage.trends import clamp_days, daily_series, run_series

    profile = _profile()
    if profile is None:
        return _unknown_profile()
    days = clamp_days(request.args.get("days"))
    return jsonify({
        "profile": profile.key,
        "days": days,
        "daily": daily_series(profile.key, days),
        "runs": run_series(profile.key, days),
    })


@api_bp.errorhandler(404)
def _not_found(e):
    return _error(404, "Ressource inconnue")
