"""Debug script: save HTML of first SeLoger card to inspect structure."""
import time
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import SELOGER_BASE_URL, SELOGER_SEARCH_URL, BROWSER_PROFILE_DIR

BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

chrome_proc = subprocess.Popen(
    ["google-chrome", "--remote-debugging-port=9222",
     f"--user-data-dir={BROWSER_PROFILE_DIR}",
     "--no-first-run", "--no-default-browser-check", "--window-size=1920,1080"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(3)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

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

    page.goto(SELOGER_SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(5)

    # Scroll to load lazy content
    page.evaluate("window.scrollTo({top: 2000, behavior: 'smooth'})")
    time.sleep(3)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1)

    selector = 'div[data-testid^="classified-card-mfe-"]'
    cards = page.query_selector_all(selector)
    print(f"Found {len(cards)} cards")

    output = Path("logs/debug_seloger_cards.html")
    with open(output, "w", encoding="utf-8") as f:
        for i, card in enumerate(cards[:3]):
            html = card.evaluate("el => el.outerHTML")
            text = card.inner_text()
            f.write(f"\n{'='*80}\nCARD {i+1}\n{'='*80}\n")
            f.write(f"\n--- INNER TEXT ---\n{text}\n")
            f.write(f"\n--- HTML ---\n{html}\n")
            print(f"\nCard {i+1} inner_text:\n{text}\n")

    print(f"\nSaved to {output}")
    browser.close()

chrome_proc.terminate()
