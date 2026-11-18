// ui/static/topbar.js — barre du haut commune : menus (popover natif), thème, scraping.
// Les menus .tb-menu de la page (ex. tri) profitent du même placement et du même clavier.
// Ouverture / fermeture / Échap / clic extérieur : gérés par l'attribut popover du navigateur.

function topbarCsrf() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

function storageGet(store, key) { try { return store.getItem(key); } catch (e) { return null; } }
function storageSet(store, key, value) { try { store.setItem(key, value); } catch (e) {} }
function storageDel(store, key) { try { store.removeItem(key); } catch (e) {} }

/* ---- Profil courant : mémorisé pour les pages sans profil (poids, LLM) ---- */
function currentProfile() {
  return document.body.dataset.profile || storageGet(localStorage, 'lastProfile') || '';
}

(function rememberProfile() {
  var key = document.body.dataset.profile;
  if (key) { storageSet(localStorage, 'lastProfile', key); return; }
  key = storageGet(localStorage, 'lastProfile');
  if (!key) return;
  // Annonces, Tendances et Critères ramènent au dernier profil consulté
  document.querySelectorAll('.topbar [data-nav]').forEach(function(a) {
    var url = new URL(a.href, location.href);
    url.searchParams.set('profile', key);
    a.href = url.pathname + url.search;
  });
})();

/* ---- Popovers : placés sous leur bouton, clavier dans les menus ---- */
var TOPBAR_GUTTER = 16;

function invokerOf(pop) {
  return document.querySelector('[popovertarget="' + pop.id + '"]');
}

function placePopover(pop) {
  var btn = invokerOf(pop);
  if (!btn) return;
  var r = btn.getBoundingClientRect();
  var vw = document.documentElement.clientWidth;
  var w = Math.min(pop.offsetWidth, vw - 2 * TOPBAR_GUTTER);
  // Aligné sur le bord gauche du bouton s'il est dans la moitié gauche, sinon sur son bord droit
  var left = r.left + r.width / 2 < vw / 2 ? r.left : r.right - w;
  left = Math.max(TOPBAR_GUTTER, Math.min(left, vw - TOPBAR_GUTTER - w));
  pop.style.top = (r.bottom + 6) + 'px';
  pop.style.left = left + 'px';
}

function menuItems(menu) {
  return Array.prototype.slice.call(menu.querySelectorAll('[role="menuitem"]'))
    .filter(function(el) { return el.offsetParent !== null; });  // ignore les entrées masquées (mobile)
}

document.querySelectorAll('[popover].tb-menu, [popover].tb-panel').forEach(function(pop) {
  var btn = invokerOf(pop);
  pop.addEventListener('toggle', function(e) {
    var open = e.newState === 'open';
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) return;
    placePopover(pop);
    if (pop.getAttribute('role') === 'menu') {
      var items = menuItems(pop);
      var current = items.filter(function(el) { return el.hasAttribute('aria-current'); })[0] || items[0];
      if (current) current.focus();
    }
  });
  if (btn) btn.setAttribute('aria-expanded', 'false');
});

document.querySelectorAll('.tb-menu[role="menu"]').forEach(function(menu) {
  menu.addEventListener('keydown', function(e) {
    var items = menuItems(menu);
    var i = items.indexOf(document.activeElement);
    var next = null;
    if (e.key === 'ArrowDown') next = items[(i + 1) % items.length];
    else if (e.key === 'ArrowUp') next = items[(i - 1 + items.length) % items.length];
    else if (e.key === 'Home') next = items[0];
    else if (e.key === 'End') next = items[items.length - 1];
    if (next) { e.preventDefault(); next.focus(); }
  });
});

// Les menus suivent leur bouton (ceux de la barre d'outils défilent avec la page)
function placeOpenPopovers() {
  document.querySelectorAll('.tb-menu:popover-open, .tb-panel:popover-open').forEach(placePopover);
}
window.addEventListener('resize', placeOpenPopovers);
window.addEventListener('scroll', placeOpenPopovers, { passive: true });

/* ---- Thème clair / sombre ---- */
function effectiveTheme() {
  var t = document.documentElement.dataset.theme;
  if (t) return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function syncThemeButton() {
  var btn = document.getElementById('theme-toggle');
  if (btn) btn.setAttribute('aria-pressed', effectiveTheme() === 'dark' ? 'true' : 'false');
}

(function initTheme() {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  syncThemeButton();
  btn.addEventListener('click', function() {
    var next = effectiveTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    storageSet(localStorage, 'theme', next);
    syncThemeButton();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncThemeButton);
})();

/* ---- Vider la base : confirmation saisie, vérifiée aussi côté serveur ---- */
function confirmClear(form) {
  var answer = prompt('Toutes les annonces seront supprimées.\nTapez VIDER pour confirmer :');
  if (answer === null) return false;
  form.querySelector('input[name="confirm"]').value = answer.trim();
  return true;
}

/* ---- Scraping en arrière-plan : pastille d'état + volet ---- */
var SCRAPE_LABELS = { idle: 'Inactif', running: 'En cours…', ok: 'Terminé', err: 'Erreur' };
var _scrapingPoll = null;

function showScrapeLog(line) {
  var el = document.getElementById('scrape-log');
  if (el) el.textContent = line || '';
}

function setScrapeState(state, line) {
  var tb = document.getElementById('tb-scrape');
  var label = document.getElementById('scrape-state');
  var btn = document.getElementById('btn-scrape');
  if (!tb) return;
  tb.dataset.state = state;
  tb.title = 'Scraping : ' + SCRAPE_LABELS[state].toLowerCase();
  if (label) label.textContent = SCRAPE_LABELS[state];
  if (btn) {
    btn.disabled = state === 'running';
    btn.innerHTML = state === 'running' ? '<span class="spinner"></span>Scraping en cours…' : 'Lancer le scraping';
  }
  if (line !== undefined) showScrapeLog(line);
}

function finishedState(data) {
  if (data.returncode === null || data.returncode === undefined) return 'idle';
  return data.returncode === 0 ? 'ok' : 'err';
}

function startScraping() {
  setScrapeState('running', 'Démarrage…');
  fetch('/start-scraping?profile=' + encodeURIComponent(currentProfile()), {
    method: 'POST',
    headers: { 'X-CSRF-Token': topbarCsrf() }
  })
    .then(function(r) { return r.json(); })
    .then(function() { pollScrapingStatus(); })
    .catch(function() { setScrapeState('err', 'Erreur réseau : scraping non lancé.'); });
}

function pollScrapingStatus() {
  if (_scrapingPoll) clearInterval(_scrapingPoll);
  _scrapingPoll = setInterval(function() {
    fetch('/scraping-status')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.running) { setScrapeState('running', data.last_line); return; }
        clearInterval(_scrapingPoll);
        _scrapingPoll = null;
        var state = finishedState(data);
        if (state === 'idle') state = 'ok';  // lancé hors de l'interface : pas de code retour
        setScrapeState(state, data.last_line);
        if (document.body.dataset.page === 'index') {
          // Les nouvelles annonces apparaissent ; la pastille garde son état après rechargement
          storageSet(sessionStorage, 'scrapeResult', JSON.stringify({ state: state, line: data.last_line }));
          setTimeout(function() { window.location.reload(); }, 1500);
        }
      });
  }, 3000);
}

// État au chargement : reprendre le polling si un scraping tourne déjà
(function initScrape() {
  if (!document.getElementById('tb-scrape')) return;
  var saved = null;
  try { saved = JSON.parse(storageGet(sessionStorage, 'scrapeResult') || 'null'); } catch (e) {}
  storageDel(sessionStorage, 'scrapeResult');
  fetch('/scraping-status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.running) {
        setScrapeState('running', data.last_line);
        pollScrapingStatus();
      } else if (saved && SCRAPE_LABELS[saved.state]) {
        setScrapeState(saved.state, saved.line);
      } else {
        setScrapeState(finishedState(data), data.last_line);
      }
    })
    .catch(function() {});
})();
