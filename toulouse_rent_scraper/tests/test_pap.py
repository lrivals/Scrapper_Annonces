# tests/test_pap.py
# =========================
# Sprint 4 — PAP.fr : cartes de recherche, fiche détaillée, intégration (sans Playwright).
# Les fixtures reprennent, abrégée, la structure de vraies pages capturées le 2026-11-14.
# =========================

import json
from unittest.mock import MagicMock

from config import SEARCH_PROFILES
from scrapers import SCRAPER_PATHS, SITE_NAMES, get_scraper_class
from scrapers.detail_extractors import pap_html
from scrapers.detail_extractors.pap_detail import extract_detail

APT_URL = "https://www.pap.fr/annonces/appartement-blagnac-31700-r466100091"


def card(href, price="680&nbsp;€", location="Blagnac (31700)", tags=("2&nbsp;pièces", "1 chambre", "49&nbsp;m²"),
         dpe="b", photos=("https://cdn.pap.fr/photos/pap/10/62/a/1-p2.webp",)):
    imgs = "".join(
        f'<div class="owl-item cloned"><div><img src="{p}" alt="x"></div></div>'
        f'<div class="owl-item"><div><img src="{p}" alt="x" loading="lazy"></div></div>'
        for p in photos
    )
    lis = "".join(f"<li>{t}</li>" for t in tags)
    dpe_div = f'<div class="item-thumb-dpe item-thumb-dpe-{dpe}"></div>' if dpe else ""
    return f"""
<div class="col-1-3">
  <div class="search-list-item-alt" data-piano-sp-click="{{}}">
    <div class="owl-carousel"><div class="owl-stage-outer"><a href="{href}" class="item-thumb-link"></a>
      <div class="owl-stage">{imgs}</div></div></div>
    {dpe_div}
    <div class="item-body">
      <a class="item-title" href="{href}" name="1">
        <div class="item-price-container"><span class="item-price">
          {price}          </span></div>
        <span class="h1">
          {location}        </span>
        <ul class="item-tags">{lis}</ul>
      </a>
      <p class="item-description">Résumé tronqué...</p>
    </div>
  </div>
</div>"""


SEARCH_HTML = "<html><body>" + "".join([
    card("/annonces/appartement-blagnac-31700-r466100091"),
    card("/annonces/bureaux-blagnac-r462802394", price="169&nbsp;€", location="Blagnac", tags=("10&nbsp;m²",)),
    card("/annonces/appartement-toulouse-31000-r465402053", price="1.080&nbsp;€", location="Toulouse (31000)",
         tags=("3&nbsp;pièces", "2&nbsp;chambres", "35,21&nbsp;m²"), dpe="e",
         photos=("https://cdn.pap.fr/photos/pap/a.webp", "https://cdn.pap.fr/photos/pap/b.webp")),
    card("/annonces/colocation-toulouse-31000-r465900081", price="435&nbsp;€"),
    card("/annonces/garage-parking-toulouse-31000-r465900871", price="75&nbsp;€", tags=()),
    # Même annonce rechargée par le défilement infini
    card("/annonces/appartement-blagnac-31700-r466100091"),
]) + "</body></html>"

PRODUCT = {
    "@context": "https://schema.org", "@type": "Product",
    "name": "Location appartement 2&nbsp;pièces 49&nbsp;m² Blagnac (31700)",
    "description": "Proche du parc Odyssud, appartement en rdc, une terrasse de 12 M2.\nDisponible mi-décembre.",
    "image": ["https://cdn.pap.fr/photos/pap/10/1-p1.jpg", "https://cdn.pap.fr/photos/pap/1f/1-p1.jpg"],
    "sku": "location-466100091",
    "offers": {"@type": "Offer", "url": APT_URL, "price": "680", "priceCurrency": "EUR"},
    "additionalProperty": [
        {"@type": "PropertyValue", "name": "Surface", "value": "49.00", "unitCode": "MTK"},
        {"@type": "PropertyValue", "name": "Nombre de pièces", "value": 2},
        {"@type": "PropertyValue", "name": "Type de bien", "value": "Appartement"},
        {"@type": "PropertyValue", "name": "Meublé", "value": "Non"},
        {"@type": "PropertyValue", "name": "Balcon / Terrasse", "value": "Oui"},
    ],
    "address": {"@type": "PostalAddress", "streetAddress": "Avenue de Cornebarrieu",
                "addressLocality": "Blagnac", "postalCode": "31700", "addressCountry": "FR"},
}


def detail_html(product=PRODUCT, gps='{&quot;center&quot;:[&quot;43.637980&quot;,&quot;1.380380&quot;],&quot;zoom&quot;:15}'):
    ld = f'<script type="application/ld+json">{json.dumps(product, ensure_ascii=False)}</script>' if product else ""
    return f"""<html><head>{ld}
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList"}}</script></head>
<body><div class="item-description margin-bottom-30"><h2>Blagnac (31700)</h2>
<ul class="item-tags margin-bottom-20"><li><strong>2 pièces</strong></li><li><strong>1 chambre</strong></li>
<li><strong>49&nbsp;m²</strong></li></ul>
<div class="row">
 <div class="col-1-3"><b>Loyer charges comprises</b><br>680&nbsp;€ / mois</div>
 <div class="col-1-3"><b>Dont charges</b><br>60&nbsp;€ / mois</div>
 <div class="col-1-3"><b>Dépôt de garantie</b><br>620&nbsp;€ </div>
</div>
<div class="energy-indice"><div class="item-title">Classe énergie</div>
 <ul><li>A</li><li class="active">B</li><li>C</li></ul></div>
<div class="ges-indice"><div class="item-title">GES</div>
 <ul><li>A</li><li>B</li><li class="active">C</li></ul></div>
</div>
<div id="dialog_carte"><div id="carte_mappy" data-thunderforest="{gps}"></div></div>
</body></html>"""


# --- Utilitaires ---

def test_annonce_id_and_type():
    assert pap_html.annonce_id(APT_URL) == "466100091"
    assert pap_html.annonce_id(APT_URL + "?x=1#top") == "466100091"
    assert pap_html.annonce_id("https://www.pap.fr/annonce/locations") is None
    assert pap_html.property_type(APT_URL) == "appartement"
    assert pap_html.is_living("/annonces/maison-blagnac-31700-r1234567")
    assert not pap_html.is_living("/annonces/bureaux-blagnac-r462802394")
    assert not pap_html.is_living("/annonces/colocation-toulouse-31000-r465900081")


def test_canonical_url():
    assert pap_html.canonical_url("/annonces/appartement-blagnac-31700-r466100091?utm=x") == APT_URL


# --- Recherche ---

def test_search_listings_keeps_living_only_and_dedupes():
    listings = pap_html.search_listings(SEARCH_HTML)
    assert [l.url for l in listings] == [APT_URL, "https://www.pap.fr/annonces/appartement-toulouse-31000-r465402053"]
    assert pap_html.count_cards(SEARCH_HTML) == 5


def test_card_fields():
    first, second = pap_html.search_listings(SEARCH_HTML)
    assert first.site == "PAP"
    assert first.price == 680
    assert first.location_raw == "Blagnac (31700)"
    assert (first.nb_rooms, first.nb_bedrooms, first.surface_m2) == (2, 1, 49.0)
    assert first.dpe_rating == "B"
    assert first.photos == ["https://cdn.pap.fr/photos/pap/10/62/a/1-p2.webp"]   # sans doublon « cloned »
    assert first.publisher_type == "individual"
    assert first.charges_included is True
    assert first.title == "Appartement 2 pièces 49 m² Blagnac (31700)"
    # Prix avec point des milliers, surface décimale à virgule
    assert second.price == 1080
    assert second.surface_m2 == 35.21
    assert second.dpe_rating == "E"
    assert len(second.photos) == 2


def test_card_without_description_is_not_complete():
    """Le résumé tronqué n'est pas gardé : la fiche sera ouverte (Sprint 16)."""
    listing = pap_html.search_listings(SEARCH_HTML)[0]
    assert listing.description is None
    annonce = listing.to_annonce()
    assert annonce["details"].get("enrichment_status") is None
    assert annonce["nb_rooms"] == 2
    assert annonce["details"]["extraction_source"] == "html"


def test_card_without_price_is_skipped():
    assert pap_html.parse_card(card("/annonces/appartement-blagnac-31700-r1234567", price="")) is None


# --- Fiche ---

def test_parse_detail_fields():
    d = pap_html.parse_detail(detail_html())
    assert d["surface_m2"] == 49.0
    assert d["nb_rooms"] == 2 and d["nb_bedrooms"] == 1
    assert d["floor"] == 0                       # « en rdc »
    assert d["charges"] == 60 and d["charges_included"] is True
    assert d["deposit"] == 620
    assert d["detail_price"] == 680
    assert d["furnished"] is False
    assert d["dpe_rating"] == "B" and d["ges_rating"] == "C"
    assert d["photos"] == PRODUCT["image"]
    assert d["description"].startswith("Proche du parc Odyssud")
    assert d["publisher_type"] == "individual"
    assert d["extra_attributes"]["street"] == "Avenue de Cornebarrieu"
    assert d["extra_attributes"]["balcony_or_terrace"] is True
    assert (d["lat"], d["lon"], d["geo_precision"]) == (43.63798, 1.38038, "exact")


def test_parse_detail_without_street_is_approx():
    product = {**PRODUCT, "address": {"addressLocality": "Toulouse", "postalCode": "31000"}}
    assert pap_html.parse_detail(detail_html(product))["geo_precision"] == "approx"


def test_parse_detail_without_gps():
    d = pap_html.parse_detail(detail_html(gps="pas du json"))
    assert "lat" not in d and d["surface_m2"] == 49.0


def test_parse_detail_without_product_is_none():
    assert pap_html.parse_detail(detail_html(product=None)) is None


def test_extract_detail_done_and_error():
    page = MagicMock()
    page.content.return_value = detail_html()
    result = extract_detail(page, APT_URL)
    assert result["enrichment_status"] == "done"
    assert result["extraction_source"] == "html"
    assert result["field_sources"]["surface_m2"] == "html"
    assert "detail_price" not in result["field_sources"]

    page.content.return_value = detail_html(product=None)
    assert extract_detail(page, APT_URL)["enrichment_status"] == "error"


# --- Intégration ---

def test_registry_and_profiles():
    assert "pap" in SCRAPER_PATHS and SITE_NAMES["pap"] == "PAP"
    cls = get_scraper_class("pap")
    blagnac = cls(profile=SEARCH_PROFILES["blagnac"])
    assert blagnac.site_name() == "PAP"
    assert blagnac.search_url().startswith("https://www.pap.fr/annonce/location-appartement-maison-blagnac")
    assert blagnac.annonce_key(APT_URL + "?x=1") == "466100091"
    # Profil sans URL PAP : site sauté sans ouvrir Chrome
    assert cls(profile=SEARCH_PROFILES["enac"]).scrape() == []


def test_page_json_annonces_reads_html():
    scraper = get_scraper_class("pap")(profile=SEARCH_PROFILES["blagnac"])
    page = MagicMock()
    page.content.return_value = SEARCH_HTML
    annonces = scraper.page_json_annonces(page)
    assert [a["url"] for a in annonces][0] == APT_URL
    assert all(a["site"] == "PAP" for a in annonces)


def test_enricher_uses_pap_extractor():
    from scrapers.enricher import _extractor_for
    assert _extractor_for("PAP") is extract_detail


def test_live_pap_page_is_not_expired():
    from storage.cleaner import page_shows_expired
    page = MagicMock()
    page.content.return_value = detail_html()
    page.inner_text.return_value = "Cette annonce n'est plus disponible"   # texte d'un bloc annexe
    assert page_shows_expired(page) is False
    page.content.return_value = "<html><body>Cette annonce n'est plus disponible</body></html>"
    assert page_shows_expired(page) is True


def test_cloudflare_title_counts_as_block():
    from scrapers import antibot
    page = MagicMock()
    page.url = "https://www.pap.fr/annonce/location-appartement-maison-blagnac-31700-g19307g43612"
    page.frames = []
    page.inner_text.return_value = ""
    page.content.return_value = "<html></html>"
    page.title.return_value = "Just a moment..."
    assert antibot.is_page_blocked(page, site_domain="www.pap.fr")


def test_details_panel_shows_pap_address():
    from ui.details import _attributes
    groups = _attributes("PAP", {"street": "Avenue de Cornebarrieu", "city": "Blagnac", "balcony_or_terrace": True})
    assert ("Adresse", "Avenue de Cornebarrieu, Blagnac") in groups["Logement"]
    assert (None, "Balcon / terrasse") in groups["Extérieurs & stationnement"]


def test_search_total_and_detail_budget():
    from config import DETAIL_VISITS_PER_RUN
    html = '<div data-infinite-scroll="{&quot;piano&quot;:{&quot;annonces_total&quot;:76},&quot;page&quot;:1}"></div>'
    assert pap_html.search_total(html) == 76
    assert pap_html.search_total("<html></html>") is None
    # Sans budget, aucune fiche PAP n'est ouverte par le pipeline (Sprint 16)
    assert DETAIL_VISITS_PER_RUN.get("PAP", 0) > 0
