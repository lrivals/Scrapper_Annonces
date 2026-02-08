# test_seloger_url.py
# Script de test pour vérifier quelle URL fonctionne

from playwright.sync_api import sync_playwright
import time

# URLs à tester
test_urls = [
    # URL simple - page d'accueil
    "https://www.seloger.com/",
    
    # URL de recherche simplifiée
    "https://www.seloger.com/immobilier/locations/immo-toulouse-31/",
    
    # URL avec paramètres (version originale)
    "https://www.seloger.com/list.htm?projects=1&types=1&places=[{%22inseeCodes%22:[31555]}]&priceMax=450",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
        locale="fr-FR"
    )
    
    page = context.new_page()
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}/{len(test_urls)}: {url}")
        print('='*60)
        
        try:
            page.goto(url, timeout=30000)
            time.sleep(2)
            
            title = page.title()
            print(f"✅ SUCCESS - Title: {title}")
            
            # Chercher des annonces
            articles = page.query_selector_all("article")
            print(f"📋 Trouvé {len(articles)} éléments <article>")
            
            input("Appuyez sur Enter pour continuer...")
            
        except Exception as e:
            print(f"❌ ERREUR: {e}")
            time.sleep(2)
    
    browser.close()
