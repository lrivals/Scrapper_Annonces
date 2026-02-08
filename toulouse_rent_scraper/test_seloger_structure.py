# test_seloger_structure.py
# Analyser la structure HTML de SeLoger

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        viewport={"width": 1920, "height": 1080},
        locale="fr-FR"
    )
    
    page = context.new_page()
    
    print("Navigation vers SeLoger...")
    page.goto("https://www.seloger.com/immobilier/locations/immo-toulouse-31/", 
              wait_until='networkidle', 
              timeout=60000)
    
    print("Attente 5 secondes pour le chargement JavaScript...")
    time.sleep(5)
    
    # Gérer les cookies si présent
    try:
        cookie_button = page.query_selector('button:has-text("Tout accepter")')
        if cookie_button:
            cookie_button.click()
            print("✅ Cookie popup fermée")
            time.sleep(2)
    except:
        pass
    
    print(f"\n📄 Titre: {page.title()}\n")
    
    # Chercher les liens d'annonces
    annonce_links = page.query_selector_all("a[href*='annonce']")
    print(f"🔗 {len(annonce_links)} liens d'annonces trouvés\n")
    
    if len(annonce_links) > 0:
        print("=== Analyse des 3 premiers liens ===\n")
        for i, link in enumerate(annonce_links[:3]):
            href = link.get_attribute('href')
            # Remonter au parent pour voir la structure
            parent = link.evaluate("el => el.parentElement.outerHTML")
            
            print(f"--- Lien {i+1} ---")
            print(f"URL: {href}")
            print(f"Parent HTML (100 premiers caractères):")
            print(f"{parent[:200]}...")
            print()
    
    # Essayer différents conteneurs
    print("\n=== Recherche de conteneurs d'annonces ===")
    containers = {
        "div[data-test]": "div[data-test*='listing'], div[data-test*='card'], div[data-test*='annonce']",
        "div[class*='list']": "div[class*='list']",
        "div[class*='result']": "div[class*='result']",
        "section": "section",
    }
    
    for name, selector in containers.items():
        try:
            els = page.query_selector_all(selector)
            if len(els) > 0:
                print(f"✅ {name}: {len(els)} trouvés")
                # Afficher la class du premier
                if len(els) > 0:
                    first_class = els[0].get_attribute('class')
                    first_data = els[0].get_attribute('data-test') or 'N/A'
                    print(f"   Premier élément: class='{first_class}', data-test='{first_data}'")
        except Exception as e:
            pass
    
    print("\n=== Inspection manuelle - Attendez 15 secondes ===")
    print("Ouvrez les DevTools (F12) pour inspecter la structure HTML")
    time.sleep(15)
    
    browser.close()
    print("\n✅ Test terminé")
