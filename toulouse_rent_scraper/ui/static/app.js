// ui/static/app.js — interface web des annonces
// Le profil courant et le jeton CSRF viennent du HTML (data-profile, meta csrf-token).

function csrfToken() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
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
        var dist = l.distance_km !== null ? '<br>' + l.distance_km + ' km de ' + t.label : '';
        var popup = '<b>' + (l.title || 'Annonce') + '</b>'
          + '<br>' + (l.price ? l.price + ' €/mois' : '&mdash;')
          + (l.location_raw ? '<br>' + l.location_raw : '')
          + dist
          + "<br><a href='" + l.url + "' target='_blank'>Voir l'annonce →</a>";
        L.marker([l.lat, l.lon], {icon: apptIcon})
          .addTo(_leafletMap)
          .bindPopup(popup);
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

/* Auto-restore map view if URL contains ?view=map */
(function() {
  var p = new URLSearchParams(window.location.search);
  if (p.get('view') === 'map') { setView('map'); }
})();
