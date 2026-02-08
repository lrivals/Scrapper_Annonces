# test_quick_seloger.py
# Test rapide pour diagnostiquer SeLoger

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    print("Navigation vers SeLoger...")
    page.goto("https://www.seloger.com/immobilier/locations/immo-toulouse-31/")
    
    print("Attente 5 secondes...")
    time.sleep(5)
    
    print(f"\nTitre de la page: {page.title()}")
    
    # Essayer de compter les différents éléments
    selectors = {
        "article": "article",
        "div avec class card": "div[class*='Card']",
        "div avec class listing": "div[class*='listing']",
        "a avec href annonce": "a[href*='annonce']"
    }
    
    for name, selector in selectors.items():
        try:
            elements = page.query_selector_all(selector)
            print(f"✅ {name} ({selector}): {len(elements)} trouvés")
            if len(elements) > 0 and len(elements) < 5:
                for i, el in enumerate(elements[:3]):
                    print(f"    [{i}] {el.inner_text()[:100]}")
        except Exception as e:
            print(f"❌ {name}: Erreur - {e}")
    
    print("\n=== Attendez 10s pour inspection visuelle ===")
    time.sleep(10)
    
    browser.close()
    print("✅ Test terminé")
