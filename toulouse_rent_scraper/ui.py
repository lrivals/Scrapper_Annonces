# ui.py
# =========================
# Interface web de navigation des annonces
# Usage: python main.py --ui  (ou python ui.py directement)
# =========================

import json
import logging
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from flask import Flask, request, render_template_string, redirect, make_response, jsonify

from config import DB_PATH
from storage.sqlite import init_db, clear_db, set_annonce_status

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Silence les logs verbeux de Werkzeug (requêtes HTTP Flask)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("ui")

_scraping_process = None

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
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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

    .btn-order {
      padding: 12px 14px;
      background: white;
      color: var(--text-main);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 1rem;
      font-weight: 700;
      line-height: 1;
      transition: all 0.2s;
      flex-shrink: 0;
    }
    .btn-order:hover {
      border-color: var(--text-main);
      background: #f9fafb;
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
    .dot-hidden  { background: #fca5a5; }

    .dup-tag {
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--text-muted);
      text-decoration: underline dotted;
    }

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

    /* ---- Action bar (scrape / clear DB) ---- */
    .action-bar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: center;
      margin-bottom: 6px;
    }

    .btn-scrape {
      padding: 8px 20px;
      background: #059669;
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 700;
      transition: opacity 0.2s;
    }
    .btn-scrape:hover { opacity: 0.85; }
    .btn-scrape:disabled { opacity: 0.6; cursor: not-allowed; }

    .btn-clear-db {
      padding: 8px 20px;
      background: white;
      color: #ef4444;
      border: 1.5px solid #ef4444;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 700;
      transition: all 0.2s;
    }
    .btn-clear-db:hover { background: #fef2f2; }

    @keyframes spin { to { transform: rotate(360deg); } }
    .spinner {
      display: inline-block;
      width: 12px; height: 12px;
      border: 2px solid rgba(255,255,255,0.4);
      border-top-color: white;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      vertical-align: middle;
      margin-right: 6px;
    }

    /* ---- Document mode ---- */
    .doc-bar {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: center;
    }

    .btn-doc-start {
      padding: 8px 20px;
      background: white;
      color: var(--text-main);
      border: 1.5px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 700;
      transition: all 0.2s;
    }
    .btn-doc-start:hover { border-color: var(--text-main); background: #f9fafb; }
    .btn-doc-start.active { background: var(--text-main); color: white; border-color: var(--text-main); }

    .doc-count-badge {
      font-size: 0.8125rem;
      font-weight: 600;
      color: var(--text-muted);
      display: none;
    }
    .doc-count-badge.visible { display: inline; }

    .btn-doc-export {
      padding: 8px 20px;
      background: #059669;
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 700;
      transition: opacity 0.2s;
      display: none;
    }
    .btn-doc-export:hover { opacity: 0.85; }
    .btn-doc-export.visible { display: inline-block; }

    .btn-doc-clear {
      padding: 8px 14px;
      background: none;
      color: var(--text-muted);
      border: 1px solid transparent;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 600;
      transition: all 0.2s;
      display: none;
    }
    .btn-doc-clear:hover { background: #fef2f2; color: #ef4444; }
    .btn-doc-clear.visible { display: inline-block; }

    .btn-add-doc {
      padding: 5px 12px;
      background: white;
      color: var(--text-muted);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.75rem;
      font-weight: 700;
      transition: all 0.2s;
      display: none;
    }
    .btn-add-doc:hover { border-color: #059669; color: #059669; }
    .btn-add-doc.in-doc { background: #059669; color: white; border-color: #059669; }
    body.doc-mode-active .btn-add-doc { display: inline-block; }

    .card.in-doc {
      border-color: #059669;
      box-shadow: 0 0 0 2px rgba(5, 150, 105, 0.15);
    }

    @media (max-width: 640px) {
      .filter-bar { gap: 16px; padding: 20px; position: static; }
      .grid { grid-template-columns: 1fr; }
      h1 { font-size: 2rem; }
    }

    /* ---- Card image ---- */
    .card-image {
      display: block;
      width: 100%;
      height: 180px;
      overflow: hidden;
      border-radius: 12px 12px 0 0;
      background: #f3f4f6;
      flex-shrink: 0;
      text-decoration: none;
    }

    .card-image img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      transition: transform 0.3s ease;
    }

    .card:hover .card-image img {
      transform: scale(1.03);
    }

    .card-image-placeholder {
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
      color: #9ca3af;
      font-size: 2.5rem;
    }

    /* ---- View toggle (Liste / Carte) ---- */
    .view-toggle {
      display: flex;
      gap: 8px;
    }
    .btn-view {
      padding: 8px 20px;
      background: white;
      color: var(--text-main);
      border: 1.5px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.8125rem;
      font-weight: 700;
      transition: all 0.2s;
    }
    .btn-view:hover { border-color: var(--text-main); background: #f9fafb; }
    .btn-view.active { background: var(--text-main); color: white; border-color: var(--text-main); }

    /* ---- Map container ---- */
    #map-view { margin-top: 32px; }
    #map { height: 600px; border-radius: 12px; border: 1px solid var(--border); }
    #map-ungeolocated { margin-top: 12px; font-size: 0.875rem; color: var(--text-muted); }
  </style>
</head>
<body>
  <div class="wrapper">
    <header>
      <h1>Annonces Toulouse</h1>
      <div class="count" id="annonce-count">{{ total }} annonce{{ 's' if total != 1 else '' }}</div>
      <div class="action-bar">
        <button class="btn-scrape" id="btn-scrape" onclick="startScraping()">Lancer le scraping</button>
        <form method="POST" action="/clear-db" onsubmit="return confirm('Supprimer toutes les annonces de la base ?')">
          <input type="hidden" name="back" value="{{ request.url }}">
          <button type="submit" class="btn-clear-db">Vider la BD</button>
        </form>
      </div>
      <div class="doc-bar">
        <button class="btn-doc-start" id="btn-doc-mode" onclick="toggleDocumentMode()">Commencer document</button>
        <span class="doc-count-badge" id="doc-count"></span>
        <button class="btn-doc-export" id="btn-export" onclick="exportDocument()">Exporter ↓</button>
        <button class="btn-doc-clear" id="btn-clear" onclick="clearDocument()">Vider</button>
      </div>
      <form id="doc-form" method="POST" action="/export-document" style="display:none">
        <input type="hidden" name="ids" id="doc-ids-input">
      </form>
      <div class="view-toggle">
        <button class="btn-view active" id="btn-view-list" onclick="setView('list')">&#9776; Liste</button>
        <button class="btn-view" id="btn-view-map" onclick="setView('map')">&#128506; Carte</button>
      </div>
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
          <option value="hidden" {% if current_status == 'hidden' %}selected{% endif %}>Masquées</option>
        </select>
      </div>

      <div class="filter-group">
        <label>Doublons</label>
        <select name="dups">
          <option value="" {% if current_dups == '' %}selected{% endif %}>Afficher</option>
          <option value="hide" {% if current_dups == 'hide' %}selected{% endif %}>Masquer</option>
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
        <div style="display:flex;gap:8px;align-items:center">
          <select name="sort">
            <option value="price"            {% if current_sort == 'price' %}selected{% endif %}>Prix</option>
            <option value="distance_enac_km" {% if current_sort == 'distance_enac_km' %}selected{% endif %}>Distance ENAC</option>
            <option value="created_at"       {% if current_sort == 'created_at' %}selected{% endif %}>Derniers ajouts</option>
          </select>
          <input type="hidden" id="order-input" name="order" value="{{ current_order }}">
          <button type="button" class="btn-order" id="order-btn" onclick="toggleOrder()" title="{{ 'Croissant' if current_order == 'asc' else 'Décroissant' }}">
            {{ '↑' if current_order == 'asc' else '↓' }}
          </button>
        </div>
      </div>

      <div class="filter-group">
        <button type="submit" class="btn-filter">Filtrer</button>
      </div>
      <div class="filter-group">
        <a href="/" class="btn-reset">Reset</a>
      </div>
      <input type="hidden" name="view" id="view-input" value="list">
    </form>

    <main class="grid" id="card-grid">
      {% for a in annonces %}
      <article class="card">
        <a href="{{ a.url }}" target="_blank" class="card-image">
          {% if a.thumbnail %}
            <img src="{{ a.thumbnail }}" alt="{{ a.title }}" loading="lazy" referrerpolicy="no-referrer"
                 onerror="this.parentElement.innerHTML='<div class=\'card-image-placeholder\'>🏠</div>'">
          {% else %}
            <div class="card-image-placeholder">🏠</div>
          {% endif %}
        </a>
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
            {{ {'active': 'En ligne', 'expired': 'Expiré', 'hidden': 'Masquée'}.get(s, s) }}
            {% if a.dup_url %}
            · <a href="{{ a.dup_url }}" target="_blank" class="dup-tag" title="Même bien publié sur {{ a.dup_site }}">aussi sur {{ a.dup_site }}</a>
            {% endif %}
          </div>

          <div style="display:flex;align-items:center;gap:8px">
          <button class="btn-add-doc" id="doc-btn-{{ a.id }}" onclick="toggleAnnonce({{ a.id }}, this)">+ Doc</button>
          {% if s == 'hidden' %}
          <form method="post" action="/restore" style="display:inline">
            <input type="hidden" name="id" value="{{ a.id }}">
            <input type="hidden" name="back" value="{{ back_url }}">
            <button type="submit" class="btn-add-doc" title="Restaurer l&rsquo;annonce">Restaurer</button>
          </form>
          {% else %}
          <form method="post" action="/delete" style="display:inline">
            <input type="hidden" name="id" value="{{ a.id }}">
            <input type="hidden" name="back" value="{{ back_url }}">
            <button type="submit" class="btn-del" title="Masquer (ne reviendra pas au prochain scraping)">
              <svg style="width:18px;height:18px" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
          </form>
          {% endif %}
          </div>
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

    <div id="map-view" style="display:none">
      <div id="map"></div>
      <p id="map-ungeolocated"></p>
    </div>
  </div>
  <script>
    function toggleOrder() {
      var inp = document.getElementById('order-input');
      var btn = document.getElementById('order-btn');
      if (inp.value === 'asc') {
        inp.value = 'desc';
        btn.textContent = '↓';
        btn.title = 'Décroissant';
      } else {
        inp.value = 'asc';
        btn.textContent = '↑';
        btn.title = 'Croissant';
      }
      btn.closest('form').submit();
    }

    /* ---- Document mode ---- */
    function getIds() {
      try { return JSON.parse(localStorage.getItem('documentIds') || '[]'); }
      catch(e) { return []; }
    }
    function saveIds(ids) { localStorage.setItem('documentIds', JSON.stringify(ids)); }
    function isDocMode() { return localStorage.getItem('documentMode') === 'true'; }

    function updateDocUI() {
      var ids = getIds();
      var active = isDocMode();
      var btnMode = document.getElementById('btn-doc-mode');
      var badge = document.getElementById('doc-count');
      var btnExport = document.getElementById('btn-export');
      var btnClear = document.getElementById('btn-clear');

      if (active) {
        document.body.classList.add('doc-mode-active');
        btnMode.textContent = 'Terminer';
        btnMode.classList.add('active');
      } else {
        document.body.classList.remove('doc-mode-active');
        btnMode.textContent = 'Commencer document';
        btnMode.classList.remove('active');
      }

      if (ids.length > 0) {
        badge.textContent = ids.length + ' sélectionnée' + (ids.length > 1 ? 's' : '');
        badge.classList.add('visible');
        btnExport.classList.add('visible');
        btnClear.classList.add('visible');
      } else {
        badge.classList.remove('visible');
        btnExport.classList.remove('visible');
        btnClear.classList.remove('visible');
      }

      // Mettre à jour l'état de chaque bouton de carte
      document.querySelectorAll('[id^="doc-btn-"]').forEach(function(btn) {
        var id = parseInt(btn.id.replace('doc-btn-', ''));
        var card = btn.closest('article');
        if (ids.indexOf(id) !== -1) {
          btn.textContent = '✓ Dans le doc';
          btn.classList.add('in-doc');
          if (card) card.classList.add('in-doc');
        } else {
          btn.textContent = '+ Doc';
          btn.classList.remove('in-doc');
          if (card) card.classList.remove('in-doc');
        }
      });
    }

    function toggleDocumentMode() {
      localStorage.setItem('documentMode', isDocMode() ? 'false' : 'true');
      updateDocUI();
    }

    function toggleAnnonce(id) {
      var ids = getIds();
      var idx = ids.indexOf(id);
      if (idx === -1) { ids.push(id); } else { ids.splice(idx, 1); }
      saveIds(ids);
      updateDocUI();
    }

    function clearDocument() {
      saveIds([]);
      updateDocUI();
    }

    function exportDocument() {
      var ids = getIds();
      if (ids.length === 0) { alert('Aucune annonce sélectionnée.'); return; }
      document.getElementById('doc-ids-input').value = JSON.stringify(ids);
      document.getElementById('doc-form').submit();
    }

    // Init au chargement
    updateDocUI();

    /* ---- Scraping background ---- */
    var _scrapingPoll = null;

    function startScraping() {
      var btn = document.getElementById('btn-scrape');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>Scraping en cours…';

      fetch('/start-scraping', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.status === 'already_running') {
            pollScrapingStatus();
          } else {
            pollScrapingStatus();
          }
        })
        .catch(function() {
          btn.disabled = false;
          btn.textContent = 'Lancer le scraping';
        });
    }

    function pollScrapingStatus() {
      if (_scrapingPoll) clearInterval(_scrapingPoll);
      _scrapingPoll = setInterval(function() {
        fetch('/scraping-status')
          .then(function(r) { return r.json(); })
          .then(function(data) {
            if (!data.running) {
              clearInterval(_scrapingPoll);
              _scrapingPoll = null;
              var btn = document.getElementById('btn-scrape');
              btn.disabled = false;
              btn.textContent = 'Lancer le scraping';
              setTimeout(function() { window.location.reload(); }, 1500);
            }
          });
      }, 3000);
    }

    // Reprendre le polling si un scraping est déjà en cours au chargement de la page
    fetch('/scraping-status')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.running) {
          var btn = document.getElementById('btn-scrape');
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner"></span>Scraping en cours…';
          pollScrapingStatus();
        }
      });

    // Masquage / restauration AJAX : préserve la position de scroll
    document.querySelectorAll('form[action="/delete"], form[action="/restore"]').forEach(function(form) {
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var data = new FormData(form);
        fetch(form.getAttribute('action'), {
          method: 'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          body: data
        })
        .then(function(r) { return r.json(); })
        .then(function(res) {
          if (res.ok) {
            var card = form.closest('article');
            if (card) card.remove();
            var countEl = document.getElementById('annonce-count');
            if (countEl) {
              var n = parseInt(countEl.textContent) - 1;
              countEl.textContent = n + ' annonce' + (n !== 1 ? 's' : '');
            }
            showToast('ok', res.msg);
          } else {
            showToast('err', res.msg);
          }
        })
        .catch(function() { showToast('err', 'Erreur réseau.'); });
      });
    });

    function showToast(type, msg) {
      var existing = document.querySelector('.flash');
      if (existing) existing.remove();
      var div = document.createElement('div');
      div.className = 'flash flash-' + type;
      div.textContent = msg;
      document.body.appendChild(div);
      setTimeout(function() { div.remove(); }, 3000);
    }

    /* ---- Vue carte OpenStreetMap ---- */
    var _mapInitialized = false;
    var _leafletMap = null;

    function setView(view) {
      document.getElementById('card-grid').style.display = view === 'list' ? '' : 'none';
      document.getElementById('map-view').style.display  = view === 'map'  ? '' : 'none';
      document.getElementById('btn-view-list').classList.toggle('active', view === 'list');
      document.getElementById('btn-view-map').classList.toggle('active',  view === 'map');
      var vi = document.getElementById('view-input');
      if (vi) vi.value = view;
      if (view === 'map') {
        if (!_mapInitialized) {
          _mapInitialized = true;
          initMap();
        } else {
          setTimeout(function() { _leafletMap.invalidateSize(); }, 0);
        }
      }
    }

    function initMap() {
      var enacIcon = L.divIcon({
        className: '',
        html: '<div style="width:16px;height:16px;background:#111827;border-radius:50%;border:3px solid white;box-shadow:0 1px 5px rgba(0,0,0,0.6)"></div>',
        iconSize: [16, 16], iconAnchor: [8, 8]
      });
      var apptIcon = L.divIcon({
        className: '',
        html: '<div style="width:12px;height:12px;background:#059669;border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4)"></div>',
        iconSize: [12, 12], iconAnchor: [6, 6]
      });

      var params = new URLSearchParams(window.location.search);
      fetch('/api/map-data?' + params)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          _leafletMap = L.map('map', {preferCanvas: true}).setView([data.enac.lat, data.enac.lon], 13);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          }).addTo(_leafletMap);

          L.marker([data.enac.lat, data.enac.lon], {icon: enacIcon})
            .addTo(_leafletMap)
            .bindPopup('<b>ENAC</b><br>7 Av. &Eacute;douard Belin, Toulouse');

          var ungeolocated = 0;
          data.listings.forEach(function(l) {
            if (l.lat === null || l.lon === null) { ungeolocated++; return; }
            var dist = l.distance_km !== null ? '<br>' + l.distance_km + " km de l'ENAC" : '';
            var popup = '<b>' + (l.title || 'Annonce') + '</b>'
              + '<br>' + (l.price ? l.price + ' \u20ac/mois' : '&mdash;')
              + (l.location_raw ? '<br>' + l.location_raw : '')
              + dist
              + "<br><a href='" + l.url + "' target='_blank'>Voir l'annonce \u2192</a>";
            L.marker([l.lat, l.lon], {icon: apptIcon})
              .addTo(_leafletMap)
              .bindPopup(popup);
          });

          if (ungeolocated > 0) {
            document.getElementById('map-ungeolocated').textContent =
              '\u26a0 ' + ungeolocated + ' annonce' + (ungeolocated > 1 ? 's' : '') +
              ' sans coordonn\u00e9es (adresse non g\u00e9ocode\u0301e)';
          }
        })
        .catch(function() {
          document.getElementById('map-ungeolocated').textContent =
            '\u26a0 Impossible de charger les donn\u00e9es carte.';
        });
    }

    /* Auto-restore map view if URL contains ?view=map */
    (function() {
      var p = new URLSearchParams(window.location.search);
      if (p.get('view') === 'map') { setView('map'); }
    })();
  </script>
</body>
</html>"""


ALLOWED_SORTS = {"price", "distance_enac_km", "created_at", "site"}


def _int_or_none(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_filters(site: str, status: str, prix_min: str, prix_max: str, dups: str = ""):
    """
    Construit la clause WHERE commune à la liste et à la carte (table aliasée « a »).
    Sans filtre de statut, les annonces masquées sont exclues.
    Retourne (where_sql, params, prix_min, prix_max) — prix vidés s'ils sont invalides.
    """
    where_clauses = []
    params = []

    if status:
        where_clauses.append("COALESCE(a.status, 'active') = ?")
        params.append(status)
    else:
        where_clauses.append("COALESCE(a.status, 'active') != 'hidden'")
    if site:
        where_clauses.append("a.site = ?")
        params.append(site)
    pmin = _int_or_none(prix_min)
    if pmin is not None:
        where_clauses.append("a.price >= ?")
        params.append(pmin)
    pmax = _int_or_none(prix_max)
    if pmax is not None:
        where_clauses.append("a.price <= ?")
        params.append(pmax)
    if dups == "hide":
        where_clauses.append("a.duplicate_of IS NULL")

    where_sql = "WHERE " + " AND ".join(where_clauses)
    return where_sql, params, (prix_min if pmin is not None else ""), (prix_max if pmax is not None else "")


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

    dups = request.args.get("dups", "")
    where_sql, params, prix_min, prix_max = _build_filters(site, status, prix_min, prix_max, dups)
    query = f"""
        SELECT a.*, d.site AS dup_site, d.url AS dup_url
        FROM annonces a
        LEFT JOIN annonces d ON d.id = a.duplicate_of
        {where_sql}
        ORDER BY a.{sort} {order.upper()}
    """

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(query, params).fetchall()
        annonces = [dict(r) for r in rows]
        sites = [r[0] for r in con.execute(
            "SELECT DISTINCT site FROM annonces WHERE site IS NOT NULL ORDER BY site"
        ).fetchall()]

    # Parser le JSON photos pour extraire le thumbnail (premier élément)
    for a in annonces:
        thumbnail = None
        if a.get("photos"):
            try:
                photos_list = json.loads(a["photos"])
                thumbnail = photos_list[0] if photos_list else None
            except (json.JSONDecodeError, TypeError):
                pass
        a["thumbnail"] = thumbnail

    # URL courante pour le retour après suppression
    back_url = request.url

    # Message flash passé en query param après une suppression
    flash = None
    flash_type = request.args.get("flash")
    flash_msg  = request.args.get("flash_msg", "")
    if flash_type and flash_msg:
        flash = {"type": flash_type, "msg": flash_msg}

    log.info(
        "GET / — site=%s status=%s prix=%s-%s sort=%s %s → %d annonces",
        site or "*", status or "*", prix_min or "0", prix_max or "∞", sort, order, len(annonces),
    )
    return render_template_string(
        TEMPLATE,
        annonces=annonces,
        sites=sites,
        current_site=site,
        current_status=status,
        current_dups=dups,
        current_prix_min=prix_min,
        current_prix_max=prix_max,
        current_sort=sort,
        current_order=order,
        total=len(annonces),
        back_url=back_url,
        flash=flash,
    )


def _set_status_from_form(status: str, verb: str):
    annonce_id = request.form.get("id", "").strip()
    back = request.form.get("back", "/")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def reply(ok: bool, msg: str):
        if is_ajax:
            return jsonify({"ok": ok, "msg": msg})
        return redirect(_add_flash(back, "ok" if ok else "err", msg))

    if not annonce_id or not annonce_id.isdigit():
        return reply(False, "ID invalide.")

    title = set_annonce_status(int(annonce_id), status)
    if title is None:
        return reply(False, "Annonce introuvable.")

    log.info("POST %s — id=%s titre=%s", request.path, annonce_id, title[:50])
    return reply(True, f"Annonce « {title[:50]} » {verb}.")


@app.route("/delete", methods=["POST"])
def delete():
    # Masquage (et non suppression) : l'annonce ne revient pas au prochain scraping
    return _set_status_from_form("hidden", "masquée")


@app.route("/restore", methods=["POST"])
def restore():
    return _set_status_from_form("active", "restaurée")


@app.route("/clear-db", methods=["POST"])
def clear_database():
    back = request.form.get("back", "/")
    count = clear_db()
    log.info("POST /clear-db — %d annonces supprimées", count)
    return redirect(_add_flash(back, "ok", f"Base de données vidée — {count} annonce{'s' if count != 1 else ''} supprimée{'s' if count != 1 else ''}."))


@app.route("/start-scraping", methods=["POST"])
def start_scraping():
    global _scraping_process
    if _scraping_process is not None and _scraping_process.poll() is None:
        log.info("POST /start-scraping — déjà en cours (pid=%s)", _scraping_process.pid)
        return jsonify({"status": "already_running"})
    _scraping_process = subprocess.Popen(
        [sys.executable, "main.py", "--all"],
        cwd=str(DB_PATH.parent.parent),
    )
    log.info("POST /start-scraping — démarré (pid=%s)", _scraping_process.pid)
    return jsonify({"status": "started"})


@app.route("/scraping-status")
def scraping_status():
    global _scraping_process
    if _scraping_process is None:
        log.debug("GET /scraping-status — aucun process")
        return jsonify({"running": False, "returncode": None})
    rc = _scraping_process.poll()
    log.debug("GET /scraping-status — running=%s returncode=%s", rc is None, rc)
    return jsonify({"running": rc is None, "returncode": rc})


@app.route("/export-document", methods=["POST"])
def export_document():
    raw = request.form.get("ids", "[]")
    try:
        ids = [int(i) for i in json.loads(raw)]
    except (ValueError, TypeError):
        return make_response("IDs invalides.", 400)

    if not ids:
        return make_response("Aucune annonce sélectionnée.", 400)

    placeholders = ",".join("?" * len(ids))
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM annonces WHERE id IN ({placeholders}) ORDER BY price ASC",
            ids,
        ).fetchall()
        annonces = [dict(r) for r in rows]

    today = datetime.now().strftime("%d/%m/%Y")
    fname_date = datetime.now().strftime("%Y%m%d")
    lines = [
        f"# Dossier de candidature — {today}",
        "",
        f"_{len(annonces)} annonce{'s' if len(annonces) > 1 else ''} sélectionnée{'s' if len(annonces) > 1 else ''}_",
        "",
        "---",
        "",
    ]

    for i, a in enumerate(annonces, 1):
        title = a.get("title") or f"Annonce #{a['id']}"
        url = a.get("url") or ""
        price = f"{a['price']} €/mois" if a.get("price") else "—"
        surface = f"{a['surface_m2']} m²" if a.get("surface_m2") else "—"
        rooms = str(a["nb_rooms"]) if a.get("nb_rooms") else "—"
        location = a.get("location_raw") or "Toulouse"
        dist = f"{a['distance_enac_km']:.1f} km" if a.get("distance_enac_km") is not None else "—"
        site = a.get("site") or "—"
        status = {"active": "En ligne", "expired": "Expiré", "hidden": "Masquée"}.get(a.get("status") or "active", "—")
        created = (a.get("created_at") or "")[:10] or "—"
        furnished = ("Oui" if a.get("furnished") else "Non") if a.get("furnished") is not None else "—"
        charges = f"{a['charges']} €" if a.get("charges") else "—"
        deposit = f"{a['deposit']} €" if a.get("deposit") else "—"

        lines += [
            f"## {i}. [{title}]({url})",
            "",
            f"**Plateforme :** {site}  ",
            f"**Prix :** {price}  ",
            f"**Surface :** {surface}  ",
            f"**Pièces :** {rooms}  ",
            f"**Localisation :** {location}  ",
            f"**Distance ENAC :** {dist}  ",
            f"**Meublé :** {furnished}  ",
            f"**Charges :** {charges}  ",
            f"**Dépôt de garantie :** {deposit}  ",
            f"**Statut :** {status}  ",
            f"**Ajoutée le :** {created}  ",
            "",
            "### Notes personnelles",
            "",
            "",
            "",
            "### Critères",
            "",
            "- [ ] Loyer dans le budget",
            "- [ ] Distance ENAC acceptable",
            "- [ ] Meublé / équipements OK",
            "- [ ] Disponibilité confirmée",
            "",
            "### Suivi candidature",
            "",
            "| Étape | Date | Notes |",
            "|-------|------|-------|",
            "| Premier contact | | |",
            "| Visite | | |",
            "| Dépôt dossier | | |",
            "| Réponse | | |",
            "| Décision | | |",
            "",
            "---",
            "",
        ]

    content = "\n".join(lines)
    log.info("POST /export-document — %d annonces exportées (ids=%s)", len(annonces), ids)
    resp = make_response(content)
    resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="candidatures_{fname_date}.md"'
    return resp


@app.route("/api/map-data")
def map_data():
    from config import ENAC_LATITUDE, ENAC_LONGITUDE

    site     = request.args.get("site", "")
    status   = request.args.get("status", "")
    prix_min = request.args.get("prix_min", "")
    prix_max = request.args.get("prix_max", "")

    dups     = request.args.get("dups", "")
    where_sql, params, _, _ = _build_filters(site, status, prix_min, prix_max, dups)
    query = f"""
        SELECT a.id, a.title, a.price, a.location_raw, a.distance_enac_km, a.url,
               g.latitude, g.longitude
        FROM annonces a
        LEFT JOIN geocoding_cache g ON a.location_raw = g.address
        {where_sql}
        ORDER BY a.price ASC
    """

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(query, params).fetchall()

    listings = [
        {
            "id": r["id"],
            "title": r["title"] or f"Annonce #{r['id']}",
            "price": r["price"],
            "location_raw": r["location_raw"],
            "distance_km": r["distance_enac_km"],
            "url": r["url"],
            "lat": r["latitude"],
            "lon": r["longitude"],
        }
        for r in rows
    ]

    geocoded = sum(1 for l in listings if l["lat"] is not None)
    log.info(
        "GET /api/map-data — site=%s status=%s → %d listings (%d géocodées, %d sans coords)",
        site or "*", status or "*", len(listings), geocoded, len(listings) - geocoded,
    )
    return jsonify({
        "enac": {"lat": ENAC_LATITUDE, "lon": ENAC_LONGITUDE},
        "listings": listings,
    })


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
