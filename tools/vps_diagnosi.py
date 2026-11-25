"""Diagnosi sul server italiano: l'indagine di Fossalto compare nell'elenco 'Avvisi e gare attive' di Asmecomm?"""
import re
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA, locale="it-IT")
    pg.goto("https://piattaforma.asmecomm.it/gare/index.php", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(3000)
    t = pg.inner_text("body"); print("Fossalto nell'elenco:", "fossalto" in t.lower(), "| Biferno:", "biferno" in t.lower())
    print("campi:", pg.eval_on_selector_all("input, select", "es => es.map(e => [e.tagName, e.name, e.id, e.type])")[:20])
    for sel in ["input[type=search]", "input[name*=cerca]", "input[name*=search]", "input[name*=oggetto]", "input[type=text]"]:
        try:
            pg.fill(sel, "Fossalto", timeout=3000); pg.keyboard.press("Enter"); pg.wait_for_timeout(5000); print("cercato con", sel, "->", pg.url); break
        except Exception:
            pass
    links = pg.eval_on_selector_all("a", "as => as.map(a => [(a.innerText||'').trim().slice(0,90), a.href])")
    for tt, h in links:
        if re.search(r"fossalto|biferno|ara vecchia|limosano", tt, re.I):
            print("  TROVATO:", tt.replace("\n", " "), "|", h)
    print(pg.inner_text("body")[:1200].replace("\n", " | "))
    b.close()
