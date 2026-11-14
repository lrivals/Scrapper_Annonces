# scrapers/detail_extractors/pap_detail.py
# =========================
# Fiche PAP.fr (Sprint 4.4) : JSON-LD `Product` + blocs HTML (charges, DPE, plan GPS).
# La lecture est faite par pap_html.parse_detail (testable sans navigateur) ;
# la navigation est gérée par l'appelant (enricher.py).
# =========================

from scrapers.detail_extractors.pap_html import parse_detail
from utils.logger import setup_logger

logger = setup_logger("pap_detail")

_META_KEYS = ("enrichment_status", "error_detail", "extra_attributes", "detail_price")


def extract_detail(page, url: str) -> dict:
    try:
        html = page.content()
    except Exception as e:
        return {"enrichment_status": "error", "error_detail": f"page illisible : {e}"[:200]}

    result = parse_detail(html)
    if result is None:
        return {"enrichment_status": "error", "error_detail": "fiche PAP sans JSON-LD Product"}
    if result.get("surface_m2") is None and result.get("description") is None:
        return {"enrichment_status": "error", "error_detail": "fiche PAP sans surface ni description"}

    result["field_sources"] = {
        k: "html" for k, v in result.items() if v is not None and k not in _META_KEYS
        and k not in ("lat", "lon", "geo_precision")
    }
    result["extraction_source"] = "html"
    result["enrichment_status"] = "done"
    logger.debug(
        f"PAP {url}: surface={result.get('surface_m2')}, pièces={result.get('nb_rooms')}, "
        f"DPE={result.get('dpe_rating')}, GPS={result.get('geo_precision')}"
    )
    return result
