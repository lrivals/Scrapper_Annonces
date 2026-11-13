// ui/static/app.js — interface web des annonces
// Le profil courant et le jeton CSRF viennent du HTML (data-profile, meta csrf-token).

function csrfToken() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

/* ---- Motion helpers ---- */
var EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)';
var EASE_IN = 'cubic-bezier(0.55, 0, 1, 0.45)';
var EASE_IN_OUT = 'cubic-bezier(0.65, 0, 0.35, 1)';
var DUR_ENTER = 200, DUR_EXIT = 160, DUR_MOVE = 250, DUR_WEIGHTY = 320;

function reducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
function canAnimate(el) { return el && el.animate && !reducedMotion(); }

/* Petite pulsation pour confirmer une réussite */
function pulse(el) {
  if (!canAnimate(el)) return;
  el.animate(
    [{ transform: 'scale(1)' }, { transform: 'scale(1.06)', offset: 0.4 }, { transform: 'scale(1)' }],
    { duration: DUR_WEIGHTY, easing: EASE_OUT }
  );
}
function pulseRing(el) {
  if (!canAnimate(el)) return;
  el.animate(
    [{ boxShadow: '0 0 0 0 rgba(5, 150, 105, 0.35)' }, { boxShadow: '0 0 0 10px rgba(5, 150, 105, 0)' }],
    { duration: 600, easing: EASE_OUT }
  );
}

/* Fondu enchaîné du contenu (icône / libellé) avec un peu d'échelle et de flou */
function swapText(el, text, instant) {
  if (el.textContent === text) return;
  if (instant || !canAnimate(el) || !el.offsetParent) { el.textContent = text; return; }
  var out = el.animate(
    [{ opacity: 1, transform: 'scale(1)', filter: 'blur(0)' },
     { opacity: 0, transform: 'scale(0.9)', filter: 'blur(2px)' }],
    { duration: 100, easing: EASE_IN }
  );
  out.onfinish = function() {
    el.textContent = text;
    el.animate(
      [{ opacity: 0, transform: 'scale(0.9)', filter: 'blur(2px)' },
       { opacity: 1, transform: 'scale(1)', filter: 'blur(0)' }],
      { duration: 150, easing: EASE_OUT }
    );
  };
}

/* Joue l'animation CSS de sortie (classe .is-leaving), puis appelle done */
function leave(el, done) {
  var finished = false;
  function finish() { if (!finished) { finished = true; done(); } }
  el.classList.add('is-leaving');
  el.addEventListener('animationend', finish, { once: true });
  setTimeout(finish, DUR_EXIT + 100);  // filet de sécurité
}

function showScrapeLog(line) {
  var el = document.getElementById('scrape-log');
  if (el) el.textContent = line || '';
}

/* Vider la base : confirmation saisie, vérifiée aussi côté serveur */
function confirmClear(form) {
  var answer = prompt('Toutes les annonces seront supprimées.\nTapez VIDER pour confirmer :');
  if (answer === null) return false;
  form.querySelector('input[name="confirm"]').value = answer.trim();
  return true;
}

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

var _docUIReady = false;  // pas d'animation au premier rendu

function updateDocUI() {
  var instant = !_docUIReady;
  _docUIReady = true;
  var ids = getIds();
  var active = isDocMode();
  var btnMode = document.getElementById('btn-doc-mode');
  var badge = document.getElementById('doc-count');
  var btnExport = document.getElementById('btn-export');
  var btnClear = document.getElementById('btn-clear');

  if (active) {
    document.body.classList.add('doc-mode-active');
    swapText(btnMode, 'Terminer', instant);
    btnMode.classList.add('active');
  } else {
    document.body.classList.remove('doc-mode-active');
    swapText(btnMode, 'Commencer document', instant);
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
  // Liste et pile de la vue carte (Sprint 16) : même bouton, repéré par data-id
  document.querySelectorAll('.btn-add-doc[data-id]').forEach(function(btn) {
    var id = parseInt(btn.dataset.id);
    var card = btn.closest('article');
    if (ids.indexOf(id) !== -1) {
      swapText(btn, '✓ Dans le doc', instant);
      btn.classList.add('in-doc');
      if (card) card.classList.add('in-doc');
    } else {
      swapText(btn, '+ Doc', instant);
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
  if (idx === -1) {
    var btn = document.getElementById('doc-btn-' + id);
    pulse(btn);
    pulseRing(btn && btn.closest('article'));
    pulse(document.getElementById('doc-count'));
  }
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

  fetch('/start-scraping?profile=' + encodeURIComponent(document.body.dataset.profile), {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken() }
  })
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
        showScrapeLog(data.last_line);
        if (!data.running) {
          clearInterval(_scrapingPoll);
          _scrapingPoll = null;
          var btn = document.getElementById('btn-scrape');
          btn.disabled = false;
          btn.textContent = '✓ Terminé';
          pulse(btn);
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
        if (card) {
          removeCard(card);
          // Son résumé éventuel dans la pile de la carte disparaît aussi
          var twin = document.querySelector('#map-stack-list article[data-id="' + card.dataset.id + '"]');
          if (twin) removeCard(twin);
        }
        var countEl = document.getElementById('annonce-count');
        if (countEl) {
          var n = parseInt(countEl.textContent) - 1;
          swapText(countEl, n + ' annonce' + (n !== 1 ? 's' : ''));
        }
        showToast('ok', res.msg);
      } else {
        showToast('err', res.msg);
      }
    })
    .catch(function() { showToast('err', 'Erreur réseau.'); });
  });
});

/* Retours ⭐ / 📞 / 👎 (Sprint 15.6) : un seul actif par carte ; re-cliquer l'efface */
function sendFeedback(btn) {
  var data = new FormData();
  data.append('id', btn.dataset.id);
  data.append('value', btn.dataset.value);
  data.append('profile', document.body.dataset.profile || '');
  data.append('csrf_token', csrfToken());
  fetch('/feedback', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' }, body: data })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (!res.ok) { showToast('err', res.msg); return; }
      // Même annonce dans la liste et dans la pile de la carte : on synchronise les deux
      document.querySelectorAll('.btn-fb[data-id="' + btn.dataset.id + '"]').forEach(function(b) {
        var on = b.dataset.value === res.feedback;
        b.classList.toggle('is-on', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      if (res.feedback) pulse(btn);
      showToast('ok', res.msg);
      // 👎 dans la vue par défaut (sans les 👎) : la carte sort de la liste (et de la pile)
      var fb = new URLSearchParams(window.location.search).get('fb') || '';
      if (res.feedback === 'dislike' && fb === '') {
        document.querySelectorAll('article.card[data-id="' + btn.dataset.id + '"]').forEach(removeCard);
      }
    })
    .catch(function() { showToast('err', 'Erreur réseau.'); });
}

/* Retire une carte : elle sort, puis les voisines glissent à leur nouvelle place (FLIP) */
function removeCard(card) {
  leave(card, function() {
    var grid = card.parentNode;
    var siblings = Array.prototype.filter.call(grid.children, function(c) {
      if (c === card) return false;
      var r = c.getBoundingClientRect();
      return r.bottom > -200 && r.top < window.innerHeight + 200;  // seulement autour de l'écran
    });
    var before = siblings.map(function(c) { return c.getBoundingClientRect(); });
    card.remove();
    updateStackEmpty();
    if (reducedMotion()) return;
    siblings.forEach(function(c, i) {
      var after = c.getBoundingClientRect();
      var dx = before[i].left - after.left, dy = before[i].top - after.top;
      if (!dx && !dy) return;
      c.animate(
        [{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }],
        { duration: DUR_MOVE, easing: EASE_IN_OUT }
      );
    });
  });
}

/* Toast : le nouveau entre pendant que l'ancien sort */
function dismissToast(el) {
  if (!el || el.classList.contains('is-leaving')) return;
  leave(el, function() { el.remove(); });
}

function showToast(type, msg) {
  document.querySelectorAll('.flash').forEach(dismissToast);
  var div = document.createElement('div');
  div.className = 'flash flash-' + type;
  div.textContent = msg;
  document.body.appendChild(div);
  setTimeout(function() { dismissToast(div); }, 3000);
}

/* ---- Vue carte OpenStreetMap ---- */
var _mapInitialized = false;
var _leafletMap = null;
var _markers = {};       // id annonce → {marker, listing}
var _activeId = null;    // annonce mise en avant (marqueur + résumé)
var _apptIcon = null;    // fabrique d'icônes définie dans initMap
var _mapTarget = null;   // cible du profil (pour le résumé de repli)

/* Indicateur partagé Liste / Carte : un seul élément qui se déplace */
function positionIndicator(instant) {
  var ind = document.getElementById('view-indicator');
  var active = document.querySelector('#view-toggle .btn-view.active');
  if (!ind || !active) return;
  if (instant) ind.style.transition = 'none';
  ind.style.width = active.offsetWidth + 'px';
  ind.style.transform = 'translateX(' + active.offsetLeft + 'px)';
  if (instant) { ind.offsetWidth; ind.style.transition = ''; }
}

(function initIndicator() {
  var ind = document.getElementById('view-indicator');
  if (!ind) return;
  ind.hidden = false;
  document.getElementById('view-toggle').classList.add('has-indicator');
  positionIndicator(true);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function() { positionIndicator(true); });
  }
  window.addEventListener('resize', function() { positionIndicator(true); });
})();

function setView(view, instant) {
  var current = document.getElementById('btn-view-map').classList.contains('active') ? 'map' : 'list';
  if (view === current) instant = true;
  if (!instant && document.startViewTransition && !reducedMotion()) {
    // L'ancienne vue sort pendant que la nouvelle entre ; l'indicateur glisse
    document.startViewTransition(function() { applyView(view, true); });
  } else {
    applyView(view, instant);
    if (!instant && !reducedMotion()) {
      var shown = document.getElementById(view === 'list' ? 'card-grid' : 'map-view');
      shown.classList.remove('view-enter');
      shown.offsetWidth;
      shown.classList.add('view-enter');
    }
  }
}

function applyView(view, instantIndicator) {
  document.getElementById('card-grid').style.display = view === 'list' ? '' : 'none';
  document.getElementById('map-view').style.display  = view === 'map'  ? '' : 'none';
  document.getElementById('btn-view-list').classList.toggle('active', view === 'list');
  document.getElementById('btn-view-map').classList.toggle('active',  view === 'map');
  positionIndicator(instantIndicator);
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
  if (typeof L === 'undefined') {  // Leaflet (CDN) indisponible : hors ligne, bloqué…
    document.getElementById('map-ungeolocated').textContent =
      '⚠ Impossible de charger la carte (Leaflet indisponible).';
    return;
  }
  var enacIcon = L.divIcon({
    className: '',
    html: '<div style="width:16px;height:16px;background:#111827;border-radius:50%;border:3px solid white;box-shadow:0 1px 5px rgba(0,0,0,0.6)"></div>',
    iconSize: [16, 16], iconAnchor: [8, 8]
  });
  // Couleur des marqueurs selon le score (mêmes seuils que les pastilles de la liste)
  function apptIcon(score, active) {
    var color = score === null || score === undefined ? '#9ca3af'
      : score >= 70 ? '#059669' : score >= 45 ? '#d97706' : '#9ca3af';
    return L.divIcon({
      className: active ? 'marker-active' : '',
      html: '<div style="width:12px;height:12px;background:' + color + ';border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4)"></div>',
      iconSize: [12, 12], iconAnchor: [6, 6]
    });
  }
  _apptIcon = apptIcon;

  var params = new URLSearchParams(window.location.search);
  fetch('/api/map-data?' + params)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var t = data.target;
      _mapTarget = t;
      _leafletMap = L.map('map', {preferCanvas: true}).setView([t.lat, t.lon], 12);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }).addTo(_leafletMap);

      L.marker([t.lat, t.lon], {icon: enacIcon})
        .addTo(_leafletMap)
        .bindPopup('<b>' + t.label + '</b><br>' + t.address);
      L.circle([t.lat, t.lon], {
        radius: t.radius_km * 1000, color: '#111827', weight: 1, fillOpacity: 0.04
      }).addTo(_leafletMap);

      var ungeolocated = 0;
      data.listings.forEach(function(l) {
        if (l.lat === null || l.lon === null) { ungeolocated++; return; }
        // Clic sur un point : son résumé arrive en haut de la pile à droite
        var marker = L.marker([l.lat, l.lon], {icon: apptIcon(l.score), riseOnHover: true})
          .addTo(_leafletMap)
          .bindTooltip(escapeHtml(l.title || 'Annonce') + ' · ' + (l.price ? l.price + ' €' : '—'),
                       {direction: 'top', offset: [0, -6]})
          .on('click', function() { pushToStack(l.id); });
        _markers[l.id] = {marker: marker, listing: l};
      });

      if (ungeolocated > 0) {
        document.getElementById('map-ungeolocated').textContent =
          '⚠ ' + ungeolocated + ' annonce' + (ungeolocated > 1 ? 's' : '') +
          ' sans coordonnées (adresse non géocodée)';
      }
    })
    .catch(function() {
      document.getElementById('map-ungeolocated').textContent =
        '⚠ Impossible de charger les données carte.';
    });
}

/* ---- Pile des annonces consultées (Sprint 16) ----
   Chaque clic sur un point empile son résumé en haut, sans doublon : un point déjà
   consulté voit son résumé remonter. Cliquer un résumé recentre la carte sur son point. */
function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function updateStackEmpty() {
  var list = document.getElementById('map-stack-list');
  if (!list) return;
  var empty = list.children.length === 0;
  document.getElementById('map-stack-empty').hidden = !empty;
  document.getElementById('map-stack-clear').hidden = empty;
}

/* Résumé = clone compact de la carte de la vue Liste ; repli sur les données de la carte */
function buildStackCard(id) {
  var source = document.querySelector('#card-grid article.card[data-id="' + id + '"]');
  if (source) {
    var card = source.cloneNode(true);
    card.classList.remove('is-leaving');
    card.style.removeProperty('--i');
    // Masquer / Restaurer restent dans la vue Liste (gestion AJAX propre à celle-ci)
    card.querySelectorAll('form').forEach(function(f) { f.remove(); });
    card.querySelectorAll('[id]').forEach(function(el) { el.removeAttribute('id'); });
    return card;
  }
  var l = _markers[id].listing;
  var card = document.createElement('article');
  card.className = 'card';
  card.dataset.id = id;
  var score = l.score !== null && l.score !== undefined ? Math.round(l.score) : null;
  card.innerHTML =
    '<div class="card-content">'
    + '<div class="card-header">'
    + (score !== null ? '<span class="score-pill ' + (score >= 70 ? 'score-high' : score >= 45 ? 'score-mid' : 'score-low') + '">★ ' + score + '</span>' : '')
    + '<div class="price-tag">' + (l.price ? l.price + ' €' : '—') + '</div></div>'
    + '<a class="card-title" target="_blank" href="' + escapeHtml(l.url) + '">' + escapeHtml(l.title || 'Annonce') + '</a>'
    + '<div class="card-meta">'
    + (l.location_raw ? '<div class="meta-item">' + escapeHtml(l.location_raw) + '</div>' : '')
    + (l.distance_km !== null && l.distance_km !== undefined && _mapTarget
        ? '<div class="meta-item">' + Number(l.distance_km).toFixed(1) + ' km de ' + escapeHtml(_mapTarget.label) + '</div>' : '')
    + '</div>'
    + '<a class="card-fallback-link" target="_blank" href="' + escapeHtml(l.url) + '">Voir l&rsquo;annonce →</a>'
    + '</div>';
  return card;
}

function setActive(id) {
  if (_activeId !== null && _markers[_activeId]) {
    var prev = _markers[_activeId];
    prev.marker.setIcon(_apptIcon(prev.listing.score, false));
    prev.marker.setZIndexOffset(0);
  }
  _activeId = id;
  if (id !== null && _markers[id]) {
    _markers[id].marker.setIcon(_apptIcon(_markers[id].listing.score, true));
    _markers[id].marker.setZIndexOffset(1000);
  }
  document.querySelectorAll('#map-stack-list .card').forEach(function(c) {
    c.classList.toggle('is-active', String(c.dataset.id) === String(id));
  });
}

function pushToStack(id) {
  var list = document.getElementById('map-stack-list');
  var existing = list.querySelector('article[data-id="' + id + '"]');
  if (existing) {
    if (existing !== list.firstElementChild) {
      // Remontée en tête, les autres résumés glissent à leur nouvelle place (FLIP)
      var items = Array.prototype.slice.call(list.children);
      var before = items.map(function(c) { return c.getBoundingClientRect(); });
      list.prepend(existing);
      if (!reducedMotion()) {
        items.forEach(function(c, i) {
          var after = c.getBoundingClientRect();
          var dy = before[i].top - after.top;
          if (dy) c.animate([{ transform: 'translateY(' + dy + 'px)' }, { transform: 'none' }],
                            { duration: DUR_MOVE, easing: EASE_IN_OUT });
        });
      }
    }
  } else {
    var card = buildStackCard(id);
    card.addEventListener('click', function(e) {
      if (e.target.closest('a, button, form')) return;  // liens et boutons gardent leur rôle
      focusOnMap(id);
    });
    list.prepend(card);
    updateStackEmpty();
  }
  list.scrollTo({ top: 0, behavior: reducedMotion() ? 'auto' : 'smooth' });
  setActive(id);
  updateDocUI(true);
}

/* Clic sur un résumé : la carte revient sur son point, sans réordonner la pile */
function focusOnMap(id) {
  var m = _markers[id];
  if (!m) return;
  var zoom = Math.max(_leafletMap.getZoom(), 15);
  if (reducedMotion()) _leafletMap.setView(m.marker.getLatLng(), zoom);
  else _leafletMap.flyTo(m.marker.getLatLng(), zoom, { duration: 0.6 });
  setActive(id);
}

function clearStack() {
  document.getElementById('map-stack-list').innerHTML = '';
  setActive(null);
  updateStackEmpty();
}

/* Auto-restore map view if URL contains ?view=map */
(function() {
  var p = new URLSearchParams(window.location.search);
  if (p.get('view') === 'map') { setView('map', true); }
})();
