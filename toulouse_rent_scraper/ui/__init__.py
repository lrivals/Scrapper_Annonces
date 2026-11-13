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
    from ui.llm_settings import llm_bp
    from ui.routes import bp
    from ui.security import init_security

    app = Flask(__name__)
    init_security(app)
    app.register_blueprint(bp)
    app.register_blueprint(llm_bp)

    # Signaux d'arnaque (colonne JSON) → liste, pour l'infobulle de la pastille ⚠️ (15.4)
    from analysis.llm import describe_flags
    app.jinja_env.filters["flags"] = describe_flags
    # Requêtes HTTP de Werkzeug : seulement les avertissements
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app


app = create_app()


def run_ui(host="127.0.0.1", port=5000, open_browser=True):
    init_db()  # Assure que toutes les migrations sont appliquées
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"Interface disponible sur {url}  (Ctrl+C pour arrêter)")
    app.run(host=host, port=port, debug=False, use_reloader=False)
