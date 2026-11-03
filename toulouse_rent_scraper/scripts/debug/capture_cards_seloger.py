"""Debug script: save HTML of first SeLoger card to inspect structure."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import SELOGER_BASE_URL, LOG_DIR, SEARCH_PROFILES  # noqa: E402
from scrapers.browser import chrome_session  # noqa: E402

# Usage : python scripts/debug/capture_cards_seloger.py [profil]   (défaut : enac)
PROFILE = SEARCH_PROFILES[sys.argv[1] if len(sys.argv) > 1 else "enac"]
SEARCH_URL = PROFILE.seloger_search_urls()[0]

with chrome_session() as (browser, page):

    page.goto(SELOGER_BASE_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(3)

    # Accept cookies
    try:
        btn = page.query_selector('button:has-text("Tout accepter")')
        if btn and btn.is_visible():
            btn.click()
            time.sleep(1)
    except Exception:
        pass

    page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(5)

    # Scroll to load lazy content
    page.evaluate("window.scrollTo({top: 2000, behavior: 'smooth'})")
    time.sleep(3)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1)

    selector = 'div[data-testid^="classified-card-mfe-"]'
    cards = page.query_selector_all(selector)
    print(f"Found {len(cards)} cards")

    output = LOG_DIR / "debug_seloger_cards.html"
    with open(output, "w", encoding="utf-8") as f:
        for i, card in enumerate(cards[:3]):
            html = card.evaluate("el => el.outerHTML")
            text = card.inner_text()
            f.write(f"\n{'='*80}\nCARD {i+1}\n{'='*80}\n")
            f.write(f"\n--- INNER TEXT ---\n{text}\n")
            f.write(f"\n--- HTML ---\n{html}\n")
            print(f"\nCard {i+1} inner_text:\n{text}\n")

    print(f"\nSaved to {output}")

