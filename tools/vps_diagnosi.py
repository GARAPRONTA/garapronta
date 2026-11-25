"""Diagnosi sul server italiano: dove si trova su Asmecomm l'indagine di Fossalto (codice 125392)."""
import re
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(user_agent=UA, locale="it-IT")
    for u in ["https://piattaforma.asmecomm.it/gare/dettaglio.php?codice=125392",
              "https://piattaforma.asmecomm.it/avvisi/dettaglio.php?codice=125392",
              "https://piattaforma.asmecomm.it/indagini/dettaglio.php?codice=125392",
              "https://piattaforma.asmecomm.it/gare/id125392-dettaglio",
              "https://piattaforma.asmecomm.it/gare/index.php?search=Fossalto",
              "https://piattaforma.asmecomm.it/index.php"]:
        try:
            r = pg.goto(u, wait_until="domcontentloaded", timeout=45000); pg.wait_for_timeout(2500)
            t = pg.inner_text("body")
            print(f"\n== {u}\n   -> {pg.url} · {r.status if r else ''} · Fossalto: {'fossalto' in t.lower()} · 980: {'980' in t}")
            print("   ", t[:500].replace("\n", " | "))
            links = pg.eval_on_selector_all("a", "as => as.map(a => [(a.innerText||'').trim().slice(0,60), a.href])")
            for tt, h in links:
                if re.search(r"fossalto|biferno|125392|avvis|indagin|manifestaz", tt + h, re.I):
                    print("     link:", tt.replace("\n", " "), "|", h[:150])
        except Exception as e:
            print(u, "ERR", type(e).__name__)
    b.close()
