"""Diagnosi sul server italiano: l'avviso ufficiale ANAC di Fossalto si apre con il link /bandi/<id>?"""
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA, locale="it-IT")
    pg.goto("https://pubblicitalegale.anticorruzione.it/bandi/d5c4d27e-c626-4666-90f3-55b55f5c3513", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(5000)
    t = pg.inner_text("body")
    print("Fossalto:", "fossalto" in t.lower(), "| 980:", "980" in t)
    print(t[:1500].replace("\n", " | "))
    b.close()
