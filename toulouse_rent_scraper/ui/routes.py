# ui/routes.py
# =========================
# Vues Flask — aucune requête SQL ici (voir storage/queries.py)
# =========================

import json
import subprocess
import sys
from collections import deque
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from flask import Blueprint, jsonify, make_response, redirect, render_template, request

from config import BASE_DIR, DEFAULT_PROFILE, LOG_DIR, SEARCH_PROFILES
from storage.queries import (
    SORT_COLUMNS, ListingFilters, annonces_by_ids, list_annonces, list_sites, map_listings,
)
from storage.sqlite import clear_db, set_annonce_status
from ui.export import build_candidature_markdown, candidature_filename
from ui.security import safe_back
from utils.logger import setup_logger

bp = Blueprint("ui", __name__)
log = setup_logger("ui")

SCRAPING_LOG = LOG_DIR / "ui_scraping.log"
CLEAR_DB_CONFIRMATION = "VIDER"

_scraping_process = None


def _current_profile(value):
    return SEARCH_PROFILES.get(value or "", SEARCH_PROFILES[DEFAULT_PROFILE])


def _thumbnail(photos_json):
    try:
        photos = json.loads(photos_json) if photos_json else []
    except (json.JSONDecodeError, TypeError):
        return None
    return photos[0] if photos else None


def _add_flash(url: str, ftype: str, msg: str) -> str:
    """Ajoute les params flash à une URL (en retirant les anciens si présents)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("flash", None)
    params.pop("flash_msg", None)
    params["flash"] = [ftype]
    params["flash_msg"] = [msg]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def _back() -> str:
    return safe_back(request.form.get("back", "/"))


@bp.route("/")
def index():
    profile = _current_profile(request.args.get("profile"))
    filters = ListingFilters.from_args(request.args)
    sort = request.args.get("sort", "price")
    order = request.args.get("order", "asc")
    if sort not in SORT_COLUMNS:
        sort = "price"
    if order not in ("asc", "desc"):
        order = "asc"

    annonces = list_annonces(profile.key, filters, sort, order)
    for a in annonces:
        a["thumbnail"] = _thumbnail(a.get("photos"))

    shown = filters.cleaned()
    flash = None
    if request.args.get("flash") and request.args.get("flash_msg"):
        flash = {"type": request.args["flash"], "msg": request.args["flash_msg"]}

    log.info(
        "GET / — profil=%s site=%s status=%s prix=%s-%s sort=%s %s → %d annonces",
        profile.key, shown.site or "*", shown.status or "*", shown.prix_min or "0",
        shown.prix_max or "∞", sort, order, len(annonces),
    )
    return render_template(
        "index.html",
        annonces=annonces,
        sites=list_sites(),
        current_site=shown.site,
        current_status=shown.status,
        current_dups=shown.dups,
        current_prix_min=shown.prix_min,
        current_prix_max=shown.prix_max,
        current_sort=sort,
        current_order=order,
        profile=profile,
        profiles=list(SEARCH_PROFILES.values()),
        total=len(annonces),
        back_url=request.full_path,
        flash=flash,
    )


def _set_status_from_form(status: str, verb: str):
    annonce_id = request.form.get("id", "").strip()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def reply(ok: bool, msg: str):
        if is_ajax:
            return jsonify({"ok": ok, "msg": msg})
        return redirect(_add_flash(_back(), "ok" if ok else "err", msg))

    if not annonce_id.isdigit():
        return reply(False, "ID invalide.")

    title = set_annonce_status(int(annonce_id), status)
    if title is None:
        return reply(False, "Annonce introuvable.")

    log.info("POST %s — id=%s titre=%s", request.path, annonce_id, title[:50])
    return reply(True, f"Annonce « {title[:50]} » {verb}.")


@bp.route("/delete", methods=["POST"])
def delete():
    # Masquage (et non suppression) : l'annonce ne revient pas au prochain scraping
    return _set_status_from_form("hidden", "masquée")


@bp.route("/restore", methods=["POST"])
def restore():
    return _set_status_from_form("active", "restaurée")


@bp.route("/clear-db", methods=["POST"])
def clear_database():
    if request.form.get("confirm", "").strip().upper() != CLEAR_DB_CONFIRMATION:
        return redirect(_add_flash(_back(), "err", "Base non vidée : confirmation manquante."))
    count = clear_db()
    log.info("POST /clear-db — %d annonces supprimées", count)
    plural = "s" if count != 1 else ""
    return redirect(_add_flash(_back(), "ok", f"Base de données vidée — {count} annonce{plural} supprimée{plural}."))


@bp.route("/start-scraping", methods=["POST"])
def start_scraping():
    global _scraping_process
    if _scraping_process is not None and _scraping_process.poll() is None:
        log.info("POST /start-scraping — déjà en cours (pid=%s)", _scraping_process.pid)
        return jsonify({"status": "already_running"})

    cmd = [sys.executable, "main.py", "scrape"]
    profile = request.args.get("profile", "")
    if profile in SEARCH_PROFILES:
        cmd += ["--profile", profile]

    SCRAPING_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SCRAPING_LOG, "w", encoding="utf-8") as out:
        _scraping_process = subprocess.Popen(
            cmd, cwd=str(BASE_DIR), stdout=out, stderr=subprocess.STDOUT
        )
    log.info("POST /start-scraping — démarré (pid=%s) : %s", _scraping_process.pid, " ".join(cmd[1:]))
    return jsonify({"status": "started"})


def _last_log_line() -> str:
    try:
        with open(SCRAPING_LOG, encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in deque(f, maxlen=20) if l.strip()]
    except OSError:
        return ""
    return lines[-1][:200] if lines else ""


@bp.route("/scraping-status")
def scraping_status():
    if _scraping_process is None:
        return jsonify({"running": False, "returncode": None, "last_line": ""})
    rc = _scraping_process.poll()
    return jsonify({"running": rc is None, "returncode": rc, "last_line": _last_log_line()})


@bp.route("/export-document", methods=["POST"])
def export_document():
    try:
        ids = [int(i) for i in json.loads(request.form.get("ids", "[]"))]
    except (ValueError, TypeError):
        return make_response("IDs invalides.", 400)
    if not ids:
        return make_response("Aucune annonce sélectionnée.", 400)

    profile = _current_profile(request.form.get("profile"))
    annonces = annonces_by_ids(ids, profile.key)
    log.info("POST /export-document — %d annonces exportées (ids=%s)", len(annonces), ids)

    resp = make_response(build_candidature_markdown(annonces, profile))
    resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{candidature_filename(profile)}"'
    return resp


@bp.route("/api/map-data")
def map_data():
    profile = _current_profile(request.args.get("profile"))
    listings = map_listings(profile.key, ListingFilters.from_args(request.args))
    for l in listings:
        l["title"] = l["title"] or f"Annonce #{l['id']}"

    geocoded = sum(1 for l in listings if l["lat"] is not None)
    log.info(
        "GET /api/map-data — profil=%s → %d listings (%d géocodées, %d sans coords)",
        profile.key, len(listings), geocoded, len(listings) - geocoded,
    )
    return jsonify({
        "target": {
            "key": profile.key,
            "label": profile.label,
            "address": profile.target_address,
            "lat": profile.target_lat,
            "lon": profile.target_lon,
            "radius_km": profile.max_distance_km,
        },
        "listings": [
            {k: l[k] for k in ("id", "title", "price", "location_raw", "distance_km", "url", "lat", "lon")}
            for l in listings
        ],
    })
