# ui/__init__.py
# =========================
# Interface web de navigation des annonces
# Usage : python main.py ui   (ou python -m ui)
# =========================

import logging
import threading
import webbrowser

from flask import Flask

from storage.sqlite import init_db


def create_app() -> Flask:
    from ui.api import api_bp
    from ui.llm_settings import llm_bp
    from ui.routes import bp
    from ui.security import init_security

    app = Flask(__name__)
    init_security(app)
    app.register_blueprint(bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(api_bp)

    # Signaux d'arnaque (colonne JSON) → liste, pour l'infobulle de la pastille ⚠️ (15.4)
    from analysis.llm import describe_flags
    app.jinja_env.filters["flags"] = describe_flags
    # Requêtes HTTP de Werkzeug : seulement les avertissements
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app


app = create_app()


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def run_ui(host="127.0.0.1", port=5000, open_browser=True):
    init_db()  # Assure que toutes les migrations sont appliquées
    if host not in LOCAL_HOSTS:
        # Les pages de l'interface n'ont pas d'authentification (l'API exige API_TOKEN)
        print(f"⚠ Interface ouverte sur {host} : toute personne qui atteint ce port peut l'utiliser. "
              f"Réservé à un conteneur dont le port est publié en local (Docker).")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"Interface disponible sur {url}  (Ctrl+C pour arrêter)")
    app.run(host=host, port=port, debug=False, use_reloader=False)
