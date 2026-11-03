# ui/security.py
# =========================
# Protection CSRF et redirections sûres pour l'interface locale.
# Sans cela, n'importe quelle page web visitée pourrait poster vers
# http://127.0.0.1:5000/clear-db et vider la base.
# =========================

import hmac
import os
import secrets
from urllib.parse import urlparse

from flask import abort, request, session

_SESSION_KEY = "csrf_token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token() -> str:
    """Jeton CSRF de la session (créé au premier appel)."""
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def _check_csrf():
    if request.method in _SAFE_METHODS:
        return
    expected = session.get(_SESSION_KEY)
    sent = request.form.get(_SESSION_KEY) or request.headers.get("X-CSRF-Token")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(403, description="Jeton CSRF manquant ou invalide — recharger la page.")


def init_security(app):
    # Clé de session : fixe si UI_SECRET_KEY est défini, sinon aléatoire à chaque démarrage
    # (les pages ouvertes avant un redémarrage devront être rechargées).
    app.secret_key = os.environ.get("UI_SECRET_KEY") or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(_check_csrf)


def safe_back(url: str, default: str = "/") -> str:
    """
    URL de retour limitée à l'application : chemin relatif (« /… »),
    ou URL absolue vers l'hôte courant ramenée à son chemin. Sinon `default`.
    """
    if not url:
        return default
    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in ("http", "https") or parsed.netloc != request.host:
            return default
    path = parsed.path or "/"
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return default
    return path + (f"?{parsed.query}" if parsed.query else "")
