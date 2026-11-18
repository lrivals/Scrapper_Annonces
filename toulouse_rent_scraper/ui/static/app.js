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

/* ---- Sélection pour l'export (cases à cocher des cartes + barre flottante) ---- */
// Les ids cochés restent mémorisés d'une page à l'autre (changement de filtre, de tri…)
function getIds() {
  try { return JSON.parse(localStorage.getItem('documentIds') || '[]'); }
  catch (e) { return []; }
}
function saveIds(ids) {
  try { localStorage.setItem('documentIds', JSON.stringify(ids)); } catch (e) {}
}

var _selectionReady = false;  // pas d'animation au premier rendu

function updateSelectionUI() {
  var ids = getIds();
  var bar = document.getElementById('selection-bar');
  // Liste et pile de la vue carte : même case, repérée par data-id
  document.querySelectorAll('.select-box[data-id]').forEach(function(box) {
    var on = ids.indexOf(parseInt(box.dataset.id, 10)) !== -1;
    box.checked = on;
    var card = box.closest('article');
    if (card) card.classList.toggle('is-selected', on);
  });
  document.body.classList.toggle('has-selection', ids.length > 0);
  if (!bar) return;
  var count = document.getElementById('selection-count');
  var text = ids.length + ' sélectionnée' + (ids.length > 1 ? 's' : '');
  if (ids.length > 0) {
    var wasHidden = bar.hidden;
    bar.classList.remove('is-leaving');
    bar.hidden = false;
    if (wasHidden || !_selectionReady) count.textContent = text; else swapText(count, text);
  } else if (!bar.hidden) {
    if (_selectionReady && !reducedMotion()) leave(bar, function() {
      bar.classList.remove('is-leaving');
      if (getIds().length === 0) bar.hidden = true;   // recochée pendant la sortie : la barre reste
    });
    else bar.hidden = true;
  }
  _selectionReady = true;
}

function toggleSelection(id, on) {
  var ids = getIds().filter(function(x) { return x !== id; });
  if (on) ids.push(id);
  saveIds(ids);
  updateSelectionUI();
  if (on) pulse(document.getElementById('selection-count'));
}

function clearSelection() {
  saveIds([]);
  updateSelectionUI();
}

function exportDocument() {
  var ids = getIds();
  if (ids.length === 0) return;
  document.getElementById('doc-ids-input').value = JSON.stringify(ids);
  document.getElementById('doc-form').submit();
}

document.addEventListener('change', function(e) {
  var box = e.target.closest && e.target.closest('.select-box');
  if (box) toggleSelection(parseInt(box.dataset.id, 10), box.checked);
});

// Ancien « mode document » (avant la sélection par cases) : réglage devenu inutile
try { localStorage.removeItem('documentMode'); } catch (e) {}
updateSelectionUI();

// Masquage / restauration AJAX : préserve la position de scroll
document.querySelectorAll('form[action="/delete"], form[action="/restore"]').forEach(function(form) {
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    closeMenuOf(form);
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
          if (_detailId === card.dataset.id) closeDetail();
          removeCard(card);
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

/* Menu ⋯ d'une carte : refermé dès qu'une de ses actions est lancée */
function closeMenuOf(el) {
  var pop = el.closest('[popover]');
  if (pop && pop.hidePopover && pop.matches(':popover-open')) pop.hidePopover();
}

/* Retours ⭐ / 📞 / 👎 (Sprint 15.6) : un seul actif par carte ; re-cliquer l'efface */
function sendFeedback(btn) {
  closeMenuOf(btn);
  var data = new FormData();
  data.append('id', btn.dataset.id);
  data.append('value', btn.dataset.value);
  data.append('profile', document.body.dataset.profile || '');
  data.append('csrf_token', csrfToken());
  fetch('/feedback', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' }, body: data })
    .then(function(r) { return r.json(); })
    .then(function(res) {
      if (!res.ok) { showToast('err', res.msg); return; }
      // Même annonce sur la carte de la liste, dans son menu ⋯ et dans le panneau de détail
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
        if (_detailId === btn.dataset.id) closeDetail();
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
var _activeId = null;    // annonce mise en avant (marqueur dont le détail est ouvert)
var _apptIcon = null;    // fabrique d'icônes définie dans initMap

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
  if (vi) vi.value = view === 'map' ? 'map' : '';
  keepViewInLinks(view);
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
        // Clic sur un point : son détail s'ouvre dans le panneau latéral
        var marker = L.marker([l.lat, l.lon], {icon: apptIcon(l.score), riseOnHover: true})
          .addTo(_leafletMap)
          .bindTooltip(escapeHtml(l.title || 'Annonce') + ' · ' + (l.price ? l.price + ' €' : '—'),
                       {direction: 'top', offset: [0, -6]})
          .on('click', function() { openDetail(l.id); });
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

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

/* Point de la carte mis en avant pendant que son détail est ouvert */
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
}

/* ---- Panneau de détail commun (carte de la liste ou point de la carte) ----
   Non modal : on peut cliquer une autre carte ou un autre point pendant qu'il est ouvert. */
var _detailId = null, _detailTrigger = null, _detailRequest = null;

/* Photos décalées de 30 ms à l'arrivée du contenu */
function revealPanel(panel) {
  if (!canAnimate(panel)) return;
  panel.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
                { duration: DUR_WEIGHTY, easing: EASE_OUT });
  panel.querySelectorAll('.details-photos a').forEach(function(a, i) {
    a.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }],
              { duration: DUR_ENTER, easing: EASE_OUT, delay: 60 + i * 30, fill: 'backwards' });
  });
}

/* Retours ⭐ / 📞 / 👎 du panneau : même état que la carte de la liste */
function syncDetailFeedback(id) {
  document.querySelectorAll('#detail-body .btn-fb[data-id="' + id + '"]').forEach(function(b) {
    var twin = document.querySelector('#card-grid .btn-fb.is-on[data-id="' + id + '"]');
    var on = !!twin && twin.dataset.value === b.dataset.value;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
}

function markSelectedCard(id) {
  document.querySelectorAll('#card-grid article.card.is-viewing').forEach(function(c) { c.classList.remove('is-viewing'); });
  if (id === null) return;
  var card = document.querySelector('#card-grid article.card[data-id="' + id + '"]');
  if (card) card.classList.add('is-viewing');
}

function openDetail(id, trigger) {
  var dialog = document.getElementById('detail-panel');
  var body = document.getElementById('detail-body');
  var title = document.getElementById('detail-title');
  if (!dialog) return;
  id = String(id);
  _detailTrigger = trigger || document.activeElement;
  if (!dialog.open) dialog.show();
  title.focus({ preventScroll: true });
  markSelectedCard(id);
  if (_markers[id]) setActive(id);
  if (_detailId === id && body.dataset.loaded === 'yes') return;

  _detailId = id;
  body.dataset.loaded = 'loading';
  var card = document.querySelector('#card-grid article.card[data-id="' + id + '"]');
  var cardTitle = card && card.querySelector('.card-title');
  title.textContent = cardTitle ? cardTitle.textContent.trim() : 'Annonce';
  body.innerHTML = '<p class="details-empty">Chargement…</p>';
  body.scrollTop = 0;
  if (_detailRequest) _detailRequest.abort();
  _detailRequest = window.AbortController ? new AbortController() : null;
  fetch('/annonce/' + encodeURIComponent(id) + '/details?profile=' + encodeURIComponent(document.body.dataset.profile),
        _detailRequest ? { signal: _detailRequest.signal } : {})
    .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
    .then(function(html) {
      if (_detailId !== id) return;
      body.innerHTML = html;
      body.dataset.loaded = 'yes';
      var head = body.querySelector('.detail-head');
      if (head) title.textContent = head.dataset.title;
      syncDetailFeedback(id);
      revealPanel(body);
    })
    .catch(function(err) {
      if (err && err.name === 'AbortError') return;
      delete body.dataset.loaded;   // nouvel essai au prochain clic
      body.innerHTML = '<p class="details-empty">Détails indisponibles — réessayer plus tard.</p>';
    });
}

function closeDetail() {
  var dialog = document.getElementById('detail-panel');
  if (dialog && dialog.open) dialog.close();
}

(function initDetailPanel() {
  var dialog = document.getElementById('detail-panel');
  if (!dialog) return;
  dialog.querySelectorAll('[data-close-dialog]').forEach(function(b) { b.addEventListener('click', closeDetail); });
  dialog.addEventListener('close', function() {
    markSelectedCard(null);
    setActive(null);
    var back = _detailTrigger;
    _detailTrigger = null;
    if (back && document.contains(back) && back.focus) back.focus({ preventScroll: true });
  });
  // Échap : un dialog non modal ne se ferme pas tout seul (les menus ouverts passent avant)
  document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape' || !dialog.open || e.defaultPrevented) return;
    if (document.querySelector(':popover-open') || document.querySelector('dialog:modal')) return;
    closeDetail();
  });

  var grid = document.getElementById('card-grid');
  if (!grid) return;
  grid.addEventListener('click', function(e) {
    var card = e.target.closest('article.card');
    if (!card) return;
    var link = e.target.closest('[data-open-detail]');
    if (link) {
      // Clic molette / Ctrl / Maj : le lien garde son rôle (annonce sur le site, nouvel onglet)
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      openDetail(card.dataset.id, card.querySelector('.card-title'));
      return;
    }
    // Liens, boutons, formulaires, case de sélection et menus gardent leur rôle
    if (e.target.closest('a, button, form, input, select, label, [popover]')) return;
    if (window.getSelection && String(window.getSelection()).length) return;   // sélection de texte
    openDetail(card.dataset.id, card.querySelector('.card-title'));
  });
})();

/* Auto-restore map view if URL contains ?view=map */
(function() {
  var p = new URLSearchParams(window.location.search);
  if (p.get('view') === 'map') { setView('map', true); }
})();

/* ---- Vue courante (Liste / Carte) conservée dans l'URL et les liens de filtre ---- */
function withView(href, view) {
  var url = new URL(href, window.location.href);
  if (view === 'map') url.searchParams.set('view', 'map'); else url.searchParams.delete('view');
  return url.pathname + url.search;
}

function keepViewInLinks(view) {
  document.querySelectorAll('a[data-keep-view]').forEach(function(a) {
    a.setAttribute('href', withView(a.getAttribute('href'), view));
  });
  if (window.history && history.replaceState) {
    history.replaceState(history.state, '', withView(window.location.href, view));
  }
}

/* ---- Panneau des filtres (<dialog> latéral) ---- */
(function initFiltersDialog() {
  var dialog = document.getElementById('filters-dialog');
  var openBtn = document.getElementById('btn-filters');
  if (!dialog || !openBtn || !dialog.showModal) return;
  var form = document.getElementById('filters-form');
  var submit = document.getElementById('filters-submit');
  var pending = null, timer = null;

  openBtn.addEventListener('click', function() {
    dialog.showModal();
    openBtn.setAttribute('aria-expanded', 'true');
  });
  dialog.addEventListener('close', function() {
    openBtn.setAttribute('aria-expanded', 'false');
    openBtn.focus();
  });
  dialog.querySelectorAll('[data-close-dialog]').forEach(function(b) {
    b.addEventListener('click', function() { dialog.close(); });
  });
  // Clic sur le fond assombri (hors du panneau) : fermeture
  dialog.addEventListener('click', function(e) {
    if (e.target === dialog) dialog.close();
  });

  function params() {
    var p = new URLSearchParams();
    new FormData(form).forEach(function(v, k) { if (v !== '') p.append(k, v); });
    return p;
  }

  // « Voir N annonces » : même filtrage que la liste, via /api/map-data
  function refreshCount() {
    if (pending) pending.abort();
    pending = window.AbortController ? new AbortController() : null;
    submit.classList.add('is-counting');
    fetch('/api/map-data?' + params(), pending ? { signal: pending.signal } : {})
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var n = data.listings.length;
        submit.textContent = n === 0 ? 'Aucune annonce' : 'Voir ' + n + ' annonce' + (n > 1 ? 's' : '');
        submit.classList.remove('is-counting');
      })
      .catch(function(err) { if (!err || err.name !== 'AbortError') submit.classList.remove('is-counting'); });
  }
  form.addEventListener('input', function() {
    clearTimeout(timer);
    timer = setTimeout(refreshCount, 250);
  });

  // URL propre : les champs vides ne sont pas envoyés
  form.addEventListener('submit', function() {
    form.querySelectorAll('input, select').forEach(function(el) {
      if (el.name && el.value === '') el.disabled = true;
    });
  });
})();
