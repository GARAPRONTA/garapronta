"""Diagnosi sul server italiano: apre START Toscana e Intercent-ER con Chrome e stampa le chiamate della pagina."""
import re
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
URLS = [
    "https://start.toscana.it/tendering/tenders/048481-2026/view/detail/1",
    "https://intercenter.regione.emilia-romagna.it/trovabando/BANDO_GARA_PORTALE@17518962",
]
with sync_playwright() as p:
    b = p.chromium.launch()
    for url in URLS:
        print("\n=====", url, flush=True)
        ctx = b.new_context(user_agent=UA, locale="it-IT")
        pg = ctx.new_page()
        reqs = []
        pg.on("response", lambda r: reqs.append((r.status, r.request.resource_type, r.url[:170])))
        try:
            r = pg.goto(url, wait_until="domcontentloaded", timeout=90000)
            print("goto", r.status if r else None, flush=True)
            pg.wait_for_timeout(10000)
        except Exception as e:
            print("ERR", type(e).__name__, str(e)[:200])
        try:
            print("title:", pg.title(), "| url:", pg.url[:150])
            print("testo:", pg.inner_text("body")[:1500].replace("\n", " | "))
        except Exception as e:
            print("no body", e)
        for s, ty, u in reqs:
            if ty in ("xhr", "fetch", "document") or s >= 400:
                print("  ", s, ty, u)
        ctx.close()
