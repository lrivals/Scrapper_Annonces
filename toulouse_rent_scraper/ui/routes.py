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
    SORT_COLUMNS, ListingFilters, annonces_by_ids, count_excluded, list_annonces, list_sites,
    map_listings,
)
from filters.requirements import current_requirements, describe_requirements
from storage.sqlite import clear_db, set_annonce_status
from ui.export import build_candidature_markdown, candidature_filename
from scoring import describe as describe_score
from ui.security import safe_back
from utils.lock import is_locked
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


def _json_list(value):
    try:
        items = json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []
    return items if isinstance(items, list) else []


def _with_param(url: str, key: str, value: str) -> str:
    """Même URL avec un paramètre remplacé (lien « N annonces exclues »)."""
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    params[key] = value
    return urlunparse(parsed._replace(query=urlencode(params)))


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
    sort = request.args.get("sort", "score")
    if sort not in SORT_COLUMNS:
        sort = "score"
    # Score : meilleur d'abord ; autres tris : croissant par défaut
    order = request.args.get("order") or ("desc" if sort == "score" else "asc")
    if order not in ("asc", "desc"):
        order = "asc"

    annonces = list_annonces(profile.key, filters, sort, order)
    for a in annonces:
        a["thumbnail"] = _thumbnail(a.get("photos"))
        a["score_text"] = describe_score(a.get("score_detail"))
        a["excluded"] = _json_list(a.get("excluded_reasons"))

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
        current_excl=shown.excl,
        current_fb=shown.fb,
        requirements=describe_requirements(current_requirements(profile)),
        excluded_url=_with_param(request.full_path, "excl", "only"),
        excluded_count=count_excluded(profile.key, shown) if shown.excl != "only" else len(annonces),
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


@bp.route("/feedback", methods=["POST"])
def feedback():
    """⭐ / 📞 / 👎 (15.6) : un second clic sur le même bouton efface le retour."""
    from storage.feedback import FEEDBACK_VALUES, LABELS, get_feedback, set_feedback

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    annonce_id = request.form.get("id", "").strip()
    value = request.form.get("value", "").strip()
    profile = request.form.get("profile", "")

    def reply(ok: bool, msg: str, current=None, status=200):
        if is_ajax:
            return jsonify({"ok": ok, "msg": msg, "feedback": current}), status
        return redirect(_add_flash(_back(), "ok" if ok else "err", msg))

    if not annonce_id.isdigit():
        return reply(False, "ID invalide.", status=400)
    if profile not in SEARCH_PROFILES:
        return reply(False, "Profil inconnu.", status=400)
    if value and value not in FEEDBACK_VALUES:
        return reply(False, "Retour inconnu.", status=400)
    if value and get_feedback(int(annonce_id), profile) == value:
        value = ""   # bascule : re-cliquer retire le retour
    result = set_feedback(int(annonce_id), profile, value or None)
    if result is None:
        return reply(False, "Annonce introuvable.", status=404)
    log.info("POST /feedback — id=%s profil=%s retour=%s", annonce_id, profile, value or "effacé")
    title = result["title"][:50]
    msg = f"« {title} » : {LABELS[value]}." if value else f"Retour retiré pour « {title} »."
    return reply(True, msg, current=result["feedback"])


@bp.route("/settings/weights")
def weights_page():
    from analysis.weights import propose_weights, weights_source
    from scoring import LABELS
    from storage.feedback import feedback_counts

    flash = None
    if request.args.get("flash") and request.args.get("flash_msg"):
        flash = {"type": request.args["flash"], "msg": request.args["flash_msg"]}
    return render_template(
        "weights.html",
        proposal=propose_weights(),
        counts=feedback_counts(),
        labels=LABELS,
        source=weights_source(),
        flash=flash,
    )


@bp.route("/settings/weights", methods=["POST"])
def weights_apply():
    from analysis.weights import propose_weights, reset_weights, save_weights
    from scoring import rescore

    action = request.form.get("action")
    if action == "reset":
        changed = reset_weights()
        count = rescore()
        msg = (f"Poids de config.py rétablis — {count} scores recalculés." if changed
               else "Les poids de config.py sont déjà utilisés.")
        return redirect(_add_flash("/settings/weights", "ok", msg))
    if action != "apply":
        return redirect(_add_flash("/settings/weights", "err", "Action inconnue."))
    proposal = propose_weights()
    if not proposal.ready:
        return redirect(_add_flash("/settings/weights", "err", proposal.message))
    save_weights(proposal.proposed, proposal.samples)
    count = rescore()
    log.info("POST /settings/weights — poids appliqués %s", proposal.proposed)
    return redirect(_add_flash("/settings/weights", "ok", f"Poids appliqués — {count} scores recalculés."))


@bp.route("/settings/requirements")
def requirements_page():
    """Critères éliminatoires par profil (15.5), modifiables sans toucher à config.py."""
    from filters.requirements import DPE_ORDER, EXCLUDABLE_LEASES, LEASE_LABELS, requirements_source
    from storage.queries import ListingFilters

    profile = _current_profile(request.args.get("profile"))
    flash = None
    if request.args.get("flash") and request.args.get("flash_msg"):
        flash = {"type": request.args["flash"], "msg": request.args["flash_msg"]}
    req = current_requirements(profile)
    return render_template(
        "requirements.html",
        profile=profile,
        profiles=list(SEARCH_PROFILES.values()),
        req=req,
        summary=describe_requirements(req),
        source=requirements_source(profile),
        has_config_defaults=not profile.requirements.is_empty(),
        excluded=count_excluded(profile.key, ListingFilters()),
        leases=[(k, LEASE_LABELS[k]) for k in EXCLUDABLE_LEASES],
        dpe_letters=DPE_ORDER[:-1],
        flash=flash,
    )


@bp.route("/settings/requirements", methods=["POST"])
def requirements_apply():
    from filters.requirements import parse_requirements, reset_requirements, save_requirements
    from scoring import rescore
    from storage.queries import ListingFilters

    key = request.form.get("profile", "")
    if key not in SEARCH_PROFILES:
        return redirect(_add_flash("/settings/requirements", "err", "Profil inconnu."))
    page = f"/settings/requirements?profile={key}"
    action = request.form.get("action")
    if action == "reset":
        if not reset_requirements(key):
            return redirect(_add_flash(page, "ok", "Les critères de config.py sont déjà utilisés."))
    elif action == "save":
        req, errors = parse_requirements(request.form)
        if errors:
            return redirect(_add_flash(page, "err", "Critères non enregistrés : " + " ; ".join(errors)))
        save_requirements(key, req)
    else:
        return redirect(_add_flash(page, "err", "Action inconnue."))

    rescore([key])
    excluded = count_excluded(key, ListingFilters())
    label = SEARCH_PROFILES[key].label
    log.info("POST /settings/requirements — profil=%s action=%s → %d exclue(s)", key, action, excluded)
    what = "Critères de config.py rétablis" if action == "reset" else "Critères enregistrés"
    plural = "s" if excluded != 1 else ""
    return redirect(_add_flash(page, "ok", f"{what} pour {label} — {excluded} annonce{plural} exclue{plural}."))


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
    if is_locked():
        # Lancé ailleurs (timer systemd, terminal) : on suit simplement son avancement
        log.info("POST /start-scraping — un autre run tient le verrou")
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
    if _scraping_process is None or _scraping_process.poll() is not None:
        # Pas de run lancé par l'UI en cours : peut-être un run du timer
        external = is_locked()
        rc = None if _scraping_process is None else _scraping_process.returncode
        return jsonify({
            "running": external,
            "returncode": rc,
            "last_line": "Scraping en cours (lancé hors de l'interface)…" if external else _last_log_line(),
        })
    return jsonify({"running": True, "returncode": None, "last_line": _last_log_line()})


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
            {k: l[k] for k in ("id", "title", "price", "location_raw", "distance_km", "score", "url", "lat", "lon")}
            for l in listings
        ],
    })
