# ui.py
# =========================
# Interface web de navigation des annonces
# Usage: python main.py --ui  (ou python ui.py directement)
# =========================

import sqlite3
import threading
import webbrowser
from flask import Flask, request, render_template_string, redirect

from config import DB_PATH
from storage.sqlite import init_db

app = Flask(__name__)

TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Annonces Toulouse / ENAC</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --primary: #111827;
      --primary-hover: #000000;
      --bg: #ffffff;
      --card-bg: #ffffff;
      --text-main: #111827;
      --text-muted: #6b7280;
      --border: #e5e7eb;
      --shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
      --glass-bg: rgba(255, 255, 255, 0.9);
      --glass-border: #e5e7eb;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      line-height: 1.5;
      min-height: 100vh;
    }

    .wrapper {
      max-width: 1200px;
      margin: 0 auto;
      padding: 60px 20px;
    }

    /* ---- Header ---- */
    header {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 48px;
      text-align: center;
      align-items: center;
    }

    h1 {
      font-size: 2.5rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--text-main);
    }

    .count {
      display: inline-flex;
      align-items: center;
      padding: 6px 16px;
      background: #f9fafb;
      border: 1px solid var(--border);
      border-radius: 9999px;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--text-muted);
    }

    /* ---- Filter bar ---- */
    .filter-bar {
      position: sticky;
      top: 0;
      z-index: 50;
      background: var(--glass-bg);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 24px 0;
      display: flex;
      flex-wrap: wrap;
      gap: 24px;
      align-items: flex-end;
      margin-bottom: 60px;
      justify-content: center;
    }

    .filter-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .filter-group label {
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-muted);
    }

    .filter-bar select,
    .filter-bar input {
      padding: 12px 16px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 0.875rem;
      background: white;
      color: var(--text-main);
      transition: border-color 0.2s;
      min-width: 160px;
    }

    .filter-bar input[type="number"] { width: 110px; min-width: auto; }

    .filter-bar select:focus,
    .filter-bar input:focus {
      outline: none;
      border-color: var(--text-main);
    }

    .prix-range {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .btn-filter {
      padding: 12px 28px;
      background: var(--text-main);
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.875rem;
      font-weight: 700;
      transition: opacity 0.2s;
    }
    .btn-filter:hover {
      opacity: 0.9;
    }

    .btn-reset {
      padding: 12px 20px;
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 600;
      border: 1px solid transparent;
      border-radius: 8px;
      transition: all 0.2s;
    }
    .btn-reset:hover {
      background: #f3f4f6;
      color: var(--text-main);
    }

    /* ---- Card Grid ---- */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 32px;
    }

    .card {
      background: white;
      border: 1px solid var(--border);
      border-radius: 12px;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      display: flex;
      flex-direction: column;
      padding: 24px;
    }

    .card:hover {
      transform: translateY(-4px);
      box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.05);
      border-color: var(--text-main);
    }

    .card-content {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .site-tag {
      font-size: 0.65rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      border: 1px solid var(--border);
      padding: 2px 8px;
      border-radius: 4px;
    }

    .price-tag {
      font-size: 1.5rem;
      font-weight: 800;
      color: var(--text-main);
    }

    .card-title {
      font-size: 1.125rem;
      font-weight: 700;
      line-height: 1.3;
      color: var(--text-main);
      text-decoration: none;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      min-height: 2.6em;
    }
    .card-title:hover { text-decoration: underline; }

    .card-meta {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      font-size: 0.8125rem;
      color: var(--text-muted);
      padding: 16px 0;
      border-top: 1px solid #f3f4f6;
      border-bottom: 1px solid #f3f4f6;
    }

    .meta-item {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .meta-item svg {
      width: 14px;
      height: 14px;
      color: #9ca3af;
    }

    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 8px;
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
    }

    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
    }
    .dot-active  { background: #111827; }
    .dot-expired { background: #d1d5db; }

    .btn-del {
      background: none;
      border: none;
      color: #9ca3af;
      cursor: pointer;
      padding: 4px;
      border-radius: 4px;
      transition: all 0.2s;
    }
    .btn-del:hover {
      color: #ef4444;
      background: #fef2f2;
    }

    /* ---- Empty State ---- */
    .empty-state {
      text-align: center;
      padding: 100px 20px;
      color: var(--text-muted);
      grid-column: 1 / -1;
    }

    /* ---- Flash ---- */
    .flash {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 0.875rem;
      font-weight: 600;
      box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1);
      z-index: 100;
    }
    .flash-ok  { background: #111827; color: white; }
    .flash-err { background: #ef4444; color: white; }

    @media (max-width: 640px) {
      .filter-bar { gap: 16px; padding: 20px; position: static; }
      .grid { grid-template-columns: 1fr; }
      h1 { font-size: 2rem; }
    }
  </style>
</head>
<body>
  <div class="wrapper">
    <header>
      <h1>Annonces Toulouse</h1>
      <div class="count">{{ total }} annonce{{ 's' if total != 1 else '' }}</div>
    </header>

    {% if flash %}
    <div class="flash flash-{{ flash.type }}">{{ flash.msg }}</div>
    {% endif %}

    <form method="get" class="filter-bar">
      <div class="filter-group">
        <label>Plateforme</label>
        <select name="site">
          <option value="">Toutes</option>
          {% for s in sites %}
          <option value="{{ s }}" {% if s == current_site %}selected{% endif %}>{{ s }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="filter-group">
        <label>Statut</label>
        <select name="status">
          <option value="" {% if current_status == '' %}selected{% endif %}>Tous</option>
          <option value="active" {% if current_status == 'active' %}selected{% endif %}>Actives</option>
          <option value="expired" {% if current_status == 'expired' %}selected{% endif %}>Expirées</option>
        </select>
      </div>

      <div class="filter-group">
        <label>Prix (€)</label>
        <div class="prix-range">
          <input type="number" name="prix_min" value="{{ current_prix_min }}" placeholder="Min" min="0">
          <input type="number" name="prix_max" value="{{ current_prix_max }}" placeholder="Max" min="0">
        </div>
      </div>

      <div class="filter-group">
        <label>Trier par</label>
        <select name="sort">
          <option value="price"            {% if current_sort == 'price' %}selected{% endif %}>Prix</option>
          <option value="distance_enac_km" {% if current_sort == 'distance_enac_km' %}selected{% endif %}>Distance ENAC</option>
          <option value="created_at"       {% if current_sort == 'created_at' %}selected{% endif %}>Derniers ajouts</option>
        </select>
      </div>

      <div class="filter-group">
        <button type="submit" class="btn-filter">Filtrer</button>
      </div>
      <div class="filter-group">
        <a href="/" class="btn-reset">Reset</a>
      </div>
    </form>

    <main class="grid">
      {% for a in annonces %}
      <article class="card">
        <div class="card-content">
          <div class="card-header">
            <span class="site-tag">{{ a.site or 'Source' }}</span>
            <div class="price-tag">{{ a.price or '—' }} €</div>
          </div>

          <a href="{{ a.url }}" target="_blank" class="card-title">
            {{ a.title or 'Annonce sans titre' }}
          </a>

          <div class="card-meta">
            <div class="meta-item" title="Distance de l&rsquo;ENAC">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              {% if a.distance_enac_km is not none %}
                {{ "%.1f"|format(a.distance_enac_km | float) }} km
              {% else %}
                Distance N/A
              {% endif %}
            </div>
            
            <div class="meta-item" title="Localisation">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
              {{ (a.location_raw or 'Toulouse')[:22] }}{% if (a.location_raw or '')|length > 22 %}&hellip;{% endif %}
            </div>

            <div class="meta-item" title="Date d&rsquo;ajout">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
              {% if a.created_at %}{{ a.created_at[:10] }}{% else %}Récent{% endif %}
            </div>

            <div class="meta-item" title="Type">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path></svg>
              {{ a.surface_m2 or '—' }} m²
            </div>
          </div>
        </div>

        <div class="card-footer">
          <div class="status-pill">
            {% set s = a.status or 'active' %}
            <span class="dot dot-{{ s }}"></span>
            {{ 'En ligne' if s == 'active' else 'Expiré' }}
          </div>

          <form method="post" action="/delete" style="display:inline">
            <input type="hidden" name="id" value="{{ a.id }}">
            <input type="hidden" name="back" value="{{ back_url }}">
            <button type="submit" class="btn-del" title="Supprimer">
              <svg style="width:18px;height:18px" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
          </form>
        </div>
      </article>
      {% else %}
      <div class="empty-state">
        <p>Aucune annonce trouvée.</p>
        <br>
        <a href="/" style="color:var(--text-main); font-weight: 700;">Tout effacer</a>
      </div>
      {% endfor %}
    </main>
  </div>
</body>
</html>"""


ALLOWED_SORTS = {"price", "distance_enac_km", "created_at", "site"}


@app.route("/")
def index():
    site      = request.args.get("site", "")
    status    = request.args.get("status", "")
    prix_min  = request.args.get("prix_min", "")
    prix_max  = request.args.get("prix_max", "")
    sort      = request.args.get("sort", "price")
    order     = request.args.get("order", "asc")

    if sort not in ALLOWED_SORTS:
        sort = "price"
    if order not in ("asc", "desc"):
        order = "asc"

    where_clauses = []
    params = []

    if status:
        where_clauses.append("COALESCE(status, 'active') = ?")
        params.append(status)
    if site:
        where_clauses.append("site = ?")
        params.append(site)
    if prix_min:
        try:
            where_clauses.append("price >= ?")
            params.append(int(prix_min))
        except ValueError:
            prix_min = ""
    if prix_max:
        try:
            where_clauses.append("price <= ?")
            params.append(int(prix_max))
        except ValueError:
            prix_max = ""

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = f"SELECT * FROM annonces {where_sql} ORDER BY {sort} {order.upper()}"

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(query, params).fetchall()
        annonces = [dict(r) for r in rows]
        sites = [r[0] for r in con.execute(
            "SELECT DISTINCT site FROM annonces WHERE site IS NOT NULL ORDER BY site"
        ).fetchall()]

    # URL courante pour le retour après suppression
    back_url = request.url

    # Message flash passé en query param après une suppression
    flash = None
    flash_type = request.args.get("flash")
    flash_msg  = request.args.get("flash_msg", "")
    if flash_type and flash_msg:
        flash = {"type": flash_type, "msg": flash_msg}

    return render_template_string(
        TEMPLATE,
        annonces=annonces,
        sites=sites,
        current_site=site,
        current_status=status,
        current_prix_min=prix_min,
        current_prix_max=prix_max,
        current_sort=sort,
        current_order=order,
        total=len(annonces),
        back_url=back_url,
        flash=flash,
    )


@app.route("/delete", methods=["POST"])
def delete():
    annonce_id = request.form.get("id", "").strip()
    back = request.form.get("back", "/")

    if not annonce_id or not annonce_id.isdigit():
        return redirect(_add_flash(back, "err", "ID invalide."))

    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT title FROM annonces WHERE id = ?", (int(annonce_id),)
        )
        row = cur.fetchone()
        if row is None:
            return redirect(_add_flash(back, "err", "Annonce introuvable."))
        title = row[0] or f"#{annonce_id}"
        con.execute("DELETE FROM annonces WHERE id = ?", (int(annonce_id),))

    return redirect(_add_flash(back, "ok", f"Annonce « {title[:50]} » supprimée."))


def _add_flash(url: str, ftype: str, msg: str) -> str:
    """Ajoute les params flash à une URL (en retirant les anciens si présents)."""
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("flash", None)
    params.pop("flash_msg", None)
    params["flash"] = [ftype]
    params["flash_msg"] = [msg]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


def run_ui(host="127.0.0.1", port=5000):
    init_db()  # Assure que toutes les migrations sont appliquées
    url = f"http://{host}:{port}"
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"Interface disponible sur {url}  (Ctrl+C pour arrêter)")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_ui()
