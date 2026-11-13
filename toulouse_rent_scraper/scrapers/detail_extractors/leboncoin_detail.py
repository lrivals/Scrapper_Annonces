# scrapers/detail_extractors/leboncoin_detail.py
# =========================
# Extraction des détails d'une annonce LeBonCoin
#
# Ordre (Sprint 15.1) :
#   1. JSON embarqué `__NEXT_DATA__` (lbc_json.py) — fiable, typé, avec GPS ;
#   2. regex sur la description pour les champs que le JSON n'a pas (charges, caution) ;
#   3. DOM + regex sur la page (extraction historique) si le JSON est absent.
# `field_sources` indique d'où vient chaque champ rempli.
# =========================

import re
import time
from typing import Optional

from scrapers.browser import PlaywrightTimeoutError
from scrapers.detail_extractors.lbc_json import extract_from_html

from utils.logger import setup_logger

logger = setup_logger("leboncoin_detail")


def _text(page, *selectors) -> Optional[str]:
    """Retourne le texte du premier sélecteur trouvé, ou None."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                t = el.inner_text().strip()
                if t:
                    return t
        except Exception:
            continue
    return None


def _attr(page, attr, *selectors) -> Optional[str]:
    """Retourne un attribut du premier sélecteur trouvé, ou None."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                v = el.get_attribute(attr)
                if v:
                    return v.strip()
        except Exception:
            continue
    return None


def _regex_int(pattern: str, text: str) -> Optional[int]:
    """Cherche un entier via regex dans text."""
    if not text:
        return None
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(" ", "").replace("\xa0", ""))
        except (ValueError, IndexError):
            return None
    return None


def _regex_float(pattern: str, text: str) -> Optional[float]:
    """Cherche un float via regex dans text."""
    if not text:
        return None
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ".").replace(" ", "").replace("\xa0", ""))
        except (ValueError, IndexError):
            return None
    return None


def _extract_from_dom(page, url: str) -> dict:
    """
    Extraction historique (Sprint 3) : sélecteurs CSS puis regex sur le texte de la page.
    Utilisée en secours quand le JSON `__NEXT_DATA__` est absent ou inexploitable.
    """
    result: dict = {}

    try:
        # Vérifier 404 / page invalide
        title = ""
        try:
            title = page.title()
        except Exception:
            pass

        if "404" in title or "introuvable" in title.lower() or "not found" in title.lower():
            logger.warning(f"LBC 404 pour {url}")
            return {"enrichment_status": "error", "error_detail": "404"}

        # Attendre le contenu principal
        try:
            page.wait_for_selector(
                '[data-test-id], [data-qa-id], h1',
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
            pass

        # Scroll pour forcer le lazy-loading des images
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
        except Exception:
            pass

        # Récupérer tout le texte de page pour les regex fallback
        try:
            page_text = page.inner_text("body")
        except Exception:
            page_text = ""

        # --- Surface ---
        surface = None
        surface_text = _text(
            page,
            '[data-test-id="criteria_item_square"]',
            '[data-test-id*="surface"]',
            '[data-test-id*="area"]',
        )
        if surface_text:
            surface = _regex_float(r"([\d]+(?:[,\.]\d+)?)\s*m", surface_text)
        if surface is None:
            surface = _regex_float(r"([\d]+(?:[,\.]\d+)?)\s*m[²2]", page_text)
        result["surface_m2"] = surface

        # --- Nombre de pièces ---
        rooms = None
        rooms_text = _text(
            page,
            '[data-test-id="criteria_item_rooms_count"]',
            '[data-test-id*="rooms"]',
            '[data-test-id*="piece"]',
        )
        if rooms_text:
            rooms = _regex_int(r"(\d+)\s*pi[eè]ce", rooms_text)
            if rooms is None:
                rooms = _regex_int(r"^(\d+)$", rooms_text)
        if rooms is None:
            rooms = _regex_int(r"(\d+)\s*pi[eè]ce", page_text)
        result["nb_rooms"] = rooms

        # --- Nombre de chambres ---
        bedrooms = None
        bed_text = _text(
            page,
            '[data-test-id="criteria_item_bedrooms_count"]',
            '[data-test-id*="bedroom"]',
            '[data-test-id*="chambre"]',
        )
        if bed_text:
            bedrooms = _regex_int(r"(\d+)\s*chambre", bed_text)
            if bedrooms is None:
                bedrooms = _regex_int(r"^(\d+)$", bed_text)
        if bedrooms is None:
            bedrooms = _regex_int(r"(\d+)\s*chambre", page_text)
        result["nb_bedrooms"] = bedrooms

        # --- Étage ---
        floor = None
        floor_text = _text(
            page,
            '[data-test-id*="floor"]',
            '[data-test-id*="etage"]',
        )
        if floor_text:
            floor = _regex_int(r"(\d+)", floor_text)
        if floor is None:
            floor = _regex_int(r"(\d+)\s*(?:er|ème|e|eme)\s*[eé]tage", page_text)
        result["floor"] = floor

        # --- Description ---
        description = None
        desc_text = _text(
            page,
            '[data-test-id="description"]',
            '[itemprop="description"]',
            '[data-qa-id="adview_description"]',
            '.description',
        )
        if desc_text and len(desc_text) > 20:
            description = desc_text
        result["description"] = description

        # --- DPE ---
        dpe = None
        dpe_text = _text(
            page,
            '[data-test-id*="energy_rate"]',
            '[data-test-id*="dpe"]',
            '[data-test-id*="energy"]',
            '[data-qa-id*="dpe"]',
        )
        if dpe_text:
            m = re.search(r"\b([A-G])\b", dpe_text)
            if m:
                dpe = m.group(1)
        if dpe is None:
            m = re.search(r"DPE[^A-G]{0,30}([A-G])\b", page_text, re.IGNORECASE)
            if m:
                dpe = m.group(1)
        result["dpe_rating"] = dpe

        # --- Photos ---
        # Les images LBC sont lazy-loaded, scroll_into_view_if_needed avant extraction
        photos = []
        try:
            img_selectors = [
                'img[data-test-id*="image"]',
                'img[src*="img2.leboncoin"]',
                'img[src*="static.leboncoin"]',
            ]
            for sel in img_selectors:
                imgs = page.query_selector_all(sel)
                for img in imgs:
                    try:
                        img.scroll_into_view_if_needed()
                        time.sleep(0.1)
                    except Exception:
                        pass
                    src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    if src and src.startswith("http") and src not in photos:
                        photos.append(src)
                if photos:
                    break
        except Exception:
            pass
        result["photos"] = photos if photos else None

        # --- Charges ---
        charges = _regex_int(r"(\d+)\s*€[^0-9€\n]*charges", page_text)
        if charges is None:
            charges = _regex_int(r"charges[^0-9€\n]*(\d+)\s*€", page_text)
        result["charges"] = charges

        # --- Dépôt de garantie ---
        deposit = _regex_int(r"(\d+)\s*€[^0-9€\n]*(?:caution|d[eé]p[oô]t|garantie)", page_text)
        if deposit is None:
            deposit = _regex_int(r"(?:caution|d[eé]p[oô]t|garantie)[^0-9€\n]*(\d+)\s*€", page_text)
        result["deposit"] = deposit

        # --- Meublé ---
        # « non meublé » contient « meublé » : à tester en premier
        if re.search(r"non[\s-]+meubl", page_text, re.IGNORECASE):
            furnished = False
        else:
            furnished = bool(re.search(r"meublé", page_text, re.IGNORECASE))
        result["furnished"] = furnished

        # --- Type de contact ---
        publisher_type = None
        pub_text = _text(
            page,
            '[data-test-id*="seller-type"]',
            '[data-test-id*="publisher"]',
            '[data-qa-id*="advertiser-name"]',
        )
        if pub_text:
            if re.search(r"pro|agence|professionnel|agency", pub_text, re.IGNORECASE):
                publisher_type = "agency"
            elif re.search(r"particulier|private|individual", pub_text, re.IGNORECASE):
                publisher_type = "individual"
        if publisher_type is None:
            # Chercher dans le texte si "par un pro" ou "par un particulier"
            if re.search(r"par un pro\b", page_text, re.IGNORECASE):
                publisher_type = "agency"
            elif re.search(r"par un particulier\b", page_text, re.IGNORECASE):
                publisher_type = "individual"
        result["publisher_type"] = publisher_type

        # --- Date de publication ---
        published_at = None
        date_attr = _attr(page, "datetime", "time")
        if date_attr:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", date_attr)
            if m:
                published_at = m.group(1)
        if published_at is None:
            date_text = _text(
                page,
                '[data-test-id*="date"]',
                '[data-qa-id*="date"]',
                'time',
            )
            if date_text:
                mois = {
                    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
                    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
                    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
                }
                m2 = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_text, re.IGNORECASE)
                if m2:
                    jour, mois_str, annee = m2.group(1), m2.group(2).lower(), m2.group(3)
                    if mois_str in mois:
                        published_at = f"{annee}-{mois[mois_str]}-{int(jour):02d}"
        result["published_at"] = published_at

        result["enrichment_status"] = "done"
        logger.debug(
            f"LBC detail extrait pour {url}: surface={surface}, pièces={rooms}, DPE={dpe}"
        )

    except PlaywrightTimeoutError:
        logger.warning(f"Timeout LBC detail {url}")
        result["enrichment_status"] = "error"
        result["error_detail"] = "timeout"

    except Exception as e:
        logger.error(f"Erreur extraction LBC detail {url}: {e}", exc_info=True)
        result["enrichment_status"] = "error"
        result["error_detail"] = str(e)[:200]

    return result


# ---------------------------------------------------------------------------
# Extraction JSON d'abord (Sprint 15.1)
# ---------------------------------------------------------------------------

# Sans au moins un de ces champs, le JSON est jugé inexploitable → DOM
_CORE_FIELDS = ("surface_m2", "nb_rooms", "description")

# Champs que le DOM peut compléter quand le JSON est partiel
_DOM_FIELDS = (
    "surface_m2", "nb_rooms", "nb_bedrooms", "floor", "description", "charges",
    "deposit", "furnished", "dpe_rating", "photos", "publisher_type", "published_at",
)


def _charges_from_text(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    charges = _regex_int(r"(\d+)\s*€[^0-9€\n.]{0,25}charges", text)
    if charges is None:
        charges = _regex_int(r"charges[^0-9€\n.]{0,25}(\d+)\s*€", text)
    return charges


def _deposit_from_text(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    deposit = _regex_int(r"(\d+)\s*€[^0-9€\n.]{0,25}(?:caution|d[eé]p[oô]t|garantie)", text)
    if deposit is None:
        deposit = _regex_int(r"(?:caution|d[eé]p[oô]t|garantie)[^0-9€\n.]{0,25}(\d+)\s*€", text)
    return deposit


def _from_json(page) -> Optional[dict]:
    try:
        html = page.content()
    except Exception:
        return None
    try:
        return extract_from_html(html)
    except Exception as e:  # JSON inattendu : on ne casse pas l'enrichissement
        logger.warning(f"JSON LBC illisible : {e}")
        return None


def _sources(result: dict, source: str, sources: dict) -> dict:
    for key, value in result.items():
        if value is not None and key not in sources and key not in ("enrichment_status", "error_detail"):
            sources[key] = source
    return sources


def extract_detail(page, url: str) -> dict:
    """
    Extrait les données de détail d'une annonce LeBonCoin.
    La navigation est gérée par l'appelant (enricher.py).
    """
    parsed = _from_json(page)
    if parsed is not None:
        parsed.pop("price", None)  # le prix vient de la recherche (historique des prix)

    if parsed and any(parsed.get(f) is not None for f in _CORE_FIELDS):
        sources = _sources(parsed, "json", {})
        description = parsed.get("description")
        if parsed.get("charges") is None and parsed.get("charges_included") is not True:
            parsed["charges"] = _charges_from_text(description)
            if parsed["charges"] is not None:
                sources["charges"] = "description"
        if parsed.get("deposit") is None:
            parsed["deposit"] = _deposit_from_text(description)
            if parsed["deposit"] is not None:
                sources["deposit"] = "description"
        parsed["field_sources"] = sources
        parsed["extraction_source"] = "json"
        parsed["enrichment_status"] = "done"
        logger.debug(
            f"LBC JSON pour {url}: surface={parsed.get('surface_m2')}, "
            f"pièces={parsed.get('nb_rooms')}, DPE={parsed.get('dpe_rating')}, "
            f"GPS={parsed.get('geo_precision')}"
        )
        return parsed

    # Secours : extraction DOM, complétée par ce que le JSON partiel aurait apporté
    result = _extract_from_dom(page, url)
    if result.get("enrichment_status") != "done":
        return result
    sources = _sources({k: result.get(k) for k in _DOM_FIELDS}, "dom", {})
    if parsed:
        for key, value in parsed.items():
            if value is not None and result.get(key) is None:
                result[key] = value
                sources[key] = "json"
        result["extraction_source"] = "json+dom"
    else:
        result["extraction_source"] = "dom"
        logger.info(f"LBC : pas de JSON __NEXT_DATA__ exploitable, extraction DOM pour {url}")
    result["field_sources"] = sources
    return result
