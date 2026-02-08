"""Debug script: save HTML of first LeBonCoin cards to inspect structure."""
import time
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import LEBONCOIN_BASE_URL, LEBONCOIN_SEARCH_URL, BROWSER_PROFILE_DIR

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

    # Etape 1: page d'accueil
    print("Etape 1: page d'accueil...")
    page.goto(LEBONCOIN_BASE_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(4)

    # Accept cookies
    for sel in ['button:has-text("Tout accepter")', '#didomi-notice-agree-button']:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                print(f"Cookies acceptes ({sel})")
                time.sleep(1)
                break
        except Exception:
            continue

    # Verifier blocage
    body_text = page.inner_text("body").lower()
    if "vitesse surhumaine" in body_text or "temporairement restreint" in body_text:
        print("BLOQUE par DataDome! Attends que le blocage se leve.")
        browser.close()
        chrome_proc.terminate()
        exit(1)

    # Etape 2: page de recherche
    print(f"Etape 2: recherche ({LEBONCOIN_SEARCH_URL[:80]}...)")
    time.sleep(3)
    page.goto(LEBONCOIN_SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
    time.sleep(5)

    # Re-verifier blocage
    body_text = page.inner_text("body").lower()
    if "vitesse surhumaine" in body_text or "temporairement restreint" in body_text:
        print("BLOQUE par DataDome apres navigation!")
        browser.close()
        chrome_proc.terminate()
        exit(1)

    # Scroll pour charger les cartes lazy-loaded
    print("Scroll pour lazy-loading...")
    page_height = page.evaluate("document.body.scrollHeight")
    pos = 0
    while pos < page_height:
        pos += 400
        page.evaluate(f"window.scrollTo({{top: {pos}, behavior: 'smooth'}})")
        time.sleep(0.5)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(2)

    # Chercher les cartes
    selectors = [
        'article[data-qa-id="aditem_container"]',
        'article[data-test-id="ad"]',
        'article:has(a[href*="/ad/"])',
    ]

    cards = []
    used_selector = None
    for sel in selectors:
        cards = page.query_selector_all(sel)
        if cards:
            used_selector = sel
            break

    print(f"Found {len(cards)} cards with selector: {used_selector}")

    if not cards:
        print("Aucune carte trouvee. Sauvegarde de la page entiere pour debug...")
        with open("logs/debug_lbc_fullpage.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path="logs/debug_lbc_screenshot.png")
        print("Sauvegarde dans logs/debug_lbc_fullpage.html et logs/debug_lbc_screenshot.png")
    else:
        output = Path("logs/debug_leboncoin_cards.html")
        with open(output, "w", encoding="utf-8") as f:
            for i, card in enumerate(cards[:5]):
                html = card.evaluate("el => el.outerHTML")
                text = card.inner_text()

                # Tester les selecteurs actuels
                aria = card.get_attribute("aria-label") or "(none)"
                price_el = card.query_selector('[data-qa-id="aditem_price"]')
                price_text = price_el.inner_text() if price_el else "(not found)"
                loc_el = card.query_selector('[data-qa-id="aditem_location"]')
                loc_text = loc_el.inner_text() if loc_el else "(not found)"
                title_el = card.query_selector('[data-qa-id="aditem_title"]')
                title_text = title_el.inner_text() if title_el else "(not found)"
                link_el = card.query_selector('a[href*="/ad/"]')
                link_href = link_el.get_attribute("href") if link_el else "(not found)"

                f.write(f"\n{'='*80}\nCARD {i+1}\n{'='*80}\n")
                f.write(f"\n--- SELECTORS ---\n")
                f.write(f"aria-label: {aria}\n")
                f.write(f"aditem_title: {title_text}\n")
                f.write(f"aditem_price: {price_text}\n")
                f.write(f"aditem_location: {loc_text}\n")
                f.write(f"link href: {link_href}\n")
                f.write(f"\n--- INNER TEXT ---\n{text}\n")
                f.write(f"\n--- HTML ---\n{html}\n")

                print(f"\n--- Card {i+1} ---")
                print(f"  aria-label: {aria}")
                print(f"  title: {title_text}")
                print(f"  price: {price_text}")
                print(f"  location: {loc_text}")
                print(f"  link: {link_href}")
                print(f"  inner_text:\n{text}\n")

        print(f"\nSaved to {output}")

    browser.close()

chrome_proc.terminate()
