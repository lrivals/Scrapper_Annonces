# ui/llm_settings.py
# =========================
# Page « Connexion LLM » (Sprint 15.4-bis) : chacun branche son fournisseur, son modèle
# et sa clé. La clé est stockée dans data/llm_settings.json (ignoré par git, lisible par
# son seul propriétaire) et n'est jamais réaffichée ni écrite dans les logs.
# =========================

from flask import Blueprint, redirect, render_template, request

from analysis.providers import PROVIDERS, LlmSettings, delete_settings, load_settings, save_settings
from utils.logger import setup_logger

llm_bp = Blueprint("llm_settings", __name__)
log = setup_logger("ui")

PAGE = "/settings/llm"


def _redirect(kind: str, msg: str):
    from ui.routes import _add_flash
    return redirect(_add_flash(PAGE, kind, msg))


@llm_bp.route(PAGE)
def page():
    from storage.sqlite import init_db, llm_stats

    init_db()
    settings = load_settings()
    flash = None
    if request.args.get("flash") and request.args.get("flash_msg"):
        flash = {"type": request.args["flash"], "msg": request.args["flash_msg"]}
    return render_template(
        "llm_settings.html",
        settings=settings,
        providers=PROVIDERS,
        problems=settings.problems() if settings.provider else [],
        stats=llm_stats(),
        flash=flash,
    )


@llm_bp.route(PAGE, methods=["POST"])
def save():
    current = load_settings()
    provider = request.form.get("provider", "").strip()
    if provider not in PROVIDERS:
        return _redirect("err", "Fournisseur inconnu.")
    new = LlmSettings(
        provider=provider,
        model=request.form.get("model", "").strip(),
        base_url=request.form.get("base_url", "").strip(),
        auto=request.form.get("auto") == "on",
    )
    if new.base_url and not new.base_url.startswith(("http://", "https://")):
        return _redirect("err", "L'URL de l'API doit commencer par http:// ou https://.")

    typed_key = request.form.get("api_key", "").strip()
    if typed_key:
        new.api_key = typed_key
    elif (current.provider == new.provider
          and current.effective_base_url == new.effective_base_url):
        # Champ laissé vide : on garde la clé enregistrée, mais seulement pour le même
        # fournisseur ET la même URL — jamais envoyée à un autre service.
        new.api_key = current.api_key

    save_settings(new)
    log.info("Connexion LLM enregistrée : %s (clé %s)", new.label(), "renseignée" if new.api_key else "absente")
    problems = new.problems()
    if problems:
        return _redirect("err", "Enregistré, mais incomplet : " + "; ".join(problems) + ".")
    return _redirect("ok", f"Enregistré : {new.label()}. Testez la connexion pour vérifier.")


@llm_bp.route(PAGE + "/test", methods=["POST"])
def test():
    from analysis.llm import test_connection

    settings = load_settings()
    if not settings.ready:
        return _redirect("err", "Configuration incomplète : " + "; ".join(settings.problems()) + ".")
    result = test_connection(settings)
    log.info("Test de connexion LLM (%s) : %s", settings.label(), "ok" if result["ok"] else "échec")
    return _redirect("ok" if result["ok"] else "err", result["message"][:300])


@llm_bp.route(PAGE + "/delete", methods=["POST"])
def delete():
    delete_settings()
    log.info("Connexion LLM supprimée")
    return _redirect("ok", "Réglages et clé supprimés de cette machine.")
