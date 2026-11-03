# scrapers/detail_extractors/seloger_detail.py
# =========================
# Extraction des détails d'une annonce SeLoger
# =========================

import re
from datetime import datetime
from typing import Optional

from scrapers.browser import PlaywrightTimeoutError

from utils.logger import setup_logger

logger = setup_logger("seloger_detail")


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
    """Cherche un entier via regex dans text, retourne None si absent."""
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
    """Cherche un float via regex dans text, retourne None si absent."""
    if not text:
        return None
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ".").replace(" ", "").replace("\xa0", ""))
        except (ValueError, IndexError):
            return None
    return None


def extract_detail(page, url: str) -> dict:
    """
    Navigue sur la page SeLoger et extrait les données de détail.
    Retourne un dict avec les champs enrichis.
    La navigation est gérée par l'appelant (enricher.py).
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
            logger.warning(f"SeLoger 404 pour {url}")
            return {"enrichment_status": "error", "error_detail": "404"}

        # Attendre que le contenu principal soit chargé
        try:
            page.wait_for_selector(
                '[data-testid], .classified-header, h1',
                timeout=15_000,
            )
        except PlaywrightTimeoutError:
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
            '[data-testid*="surface"]',
            '[data-testid*="area"]',
            '[data-testid*="Surface"]',
        )
        if surface_text:
            surface = _regex_float(r"([\d\s,]+)\s*m", surface_text)
        if surface is None:
            surface = _regex_float(r"([\d]+(?:[,\.]\d+)?)\s*m[²2]", page_text)
        result["surface_m2"] = surface

        # --- Nombre de pièces ---
        rooms = None
        rooms_text = _text(
            page,
            '[data-testid*="rooms"]',
            '[data-testid*="piece"]',
            '[data-testid*="Piece"]',
            '[data-testid*="nb_rooms"]',
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
            '[data-testid*="bedroom"]',
            '[data-testid*="chambre"]',
            '[data-testid*="Chambre"]',
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
        floor_text = _text(page, '[data-testid*="floor"]', '[data-testid*="etage"]')
        if floor_text:
            floor = _regex_int(r"(\d+)", floor_text)
        if floor is None:
            floor = _regex_int(r"(\d+)\s*(?:er|ème|e|eme)\s*[eé]tage", page_text)
        result["floor"] = floor

        # --- Description ---
        description = None
        desc_text = _text(
            page,
            '[data-testid*="description"]',
            '[data-testid="classified-description"]',
            '.classified-description',
        )
        if desc_text and len(desc_text) > 20:
            description = desc_text
        else:
            # Fallback : premier <p> avec >100 caractères
            try:
                paragraphs = page.query_selector_all("p")
                for p in paragraphs:
                    t = p.inner_text().strip()
                    if len(t) > 100:
                        description = t
                        break
            except Exception:
                pass
        result["description"] = description

        # --- DPE ---
        dpe = None
        dpe_text = _text(
            page,
            '[data-testid*="dpe"]',
            '[data-testid*="energy"]',
            '[data-testid*="DPE"]',
            '[data-testid*="energyRating"]',
        )
        if dpe_text:
            m = re.search(r"\b([A-G])\b", dpe_text)
            if m:
                dpe = m.group(1)
        if dpe is None:
            m = re.search(r"DPE[^A-G]*([A-G])\b", page_text, re.IGNORECASE)
            if m:
                dpe = m.group(1)
        result["dpe_rating"] = dpe

        # --- Photos ---
        photos = []
        try:
            imgs = page.query_selector_all(
                'img[data-testid*="photo"], img[src*="seloger.com"], img[src*="sl-static"]'
            )
            for img in imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                if src and src.startswith("http") and src not in photos:
                    photos.append(src)
        except Exception:
            pass
        result["photos"] = photos if photos else None

        # --- Charges ---
        charges = _regex_int(r"(\d+)\s*€[^0-9€\n]*charges", page_text)
        if charges is None:
            charges = _regex_int(r"charges[^0-9€\n]*(\d+)\s*€", page_text)
        result["charges"] = charges

        # --- Dépôt de garantie ---
        deposit = _regex_int(r"(\d+)\s*€[^0-9€\n]*(?:d[eé]p[oô]t|garantie)", page_text)
        if deposit is None:
            deposit = _regex_int(r"(?:d[eé]p[oô]t|garantie)[^0-9€\n]*(\d+)\s*€", page_text)
        result["deposit"] = deposit

        # --- Meublé ---
        furnished = bool(re.search(r"meublé", page_text, re.IGNORECASE))
        result["furnished"] = furnished

        # --- Type de contact ---
        publisher_type = None
        pub_text = _text(
            page,
            '[data-testid*="agency"]',
            '[data-testid*="publisher"]',
            '[data-testid*="contact-type"]',
        )
        if pub_text:
            if re.search(r"agence|professionnel|agency", pub_text, re.IGNORECASE):
                publisher_type = "agency"
            elif re.search(r"particulier|private|individual", pub_text, re.IGNORECASE):
                publisher_type = "individual"
        result["publisher_type"] = publisher_type

        # --- Date de publication ---
        published_at = None
        date_text = _text(
            page,
            '[data-testid*="date"]',
            '[data-testid*="published"]',
            'time',
        )
        if not date_text:
            date_text = _attr(page, "datetime", "time")
        if date_text:
            # Essayer ISO d'abord
            m = re.search(r"(\d{4}-\d{2}-\d{2})", date_text)
            if m:
                published_at = m.group(1)
            else:
                # Format français : "15 mars 2024"
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
        logger.debug(f"SeLoger detail extrait pour {url}: surface={surface}, pièces={rooms}, DPE={dpe}")

    except PlaywrightTimeoutError:
        logger.warning(f"Timeout SeLoger detail {url}")
        result["enrichment_status"] = "error"
        result["error_detail"] = "timeout"

    except Exception as e:
        logger.error(f"Erreur extraction SeLoger detail {url}: {e}", exc_info=True)
        result["enrichment_status"] = "error"
        result["error_detail"] = str(e)[:200]

    return result
