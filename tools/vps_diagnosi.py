"""Diagnosi sul server italiano: dove stanno i documenti nelle API pubbliche di START e Intercent-ER."""
import json
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def corto(o, d=0):
    if isinstance(o, dict):
        return {k: corto(v, d + 1) for k, v in list(o.items())[:40]} if d < 4 else "{...}"
    if isinstance(o, list):
        return [corto(x, d + 1) for x in o[:3]] + ([f"...+{len(o)-3}"] if len(o) > 3 else [])
    return o if not isinstance(o, str) else o[:90]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(user_agent=UA, locale="it-IT")
    pg.goto("https://start.toscana.it/tendering/tenders/048481-2026/view/detail/1", wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(6000)
    for api in ["/tendering-api/tenders/open_procedure/048481-2026/basic-info",
                "/tendering-api/tenders/open_procedure/048481-2026/notices",
                "/tendering-api/doc-procedure/tenders/048481-2026/doc-procedure-count",
                "/tendering-api/tenders/open_procedure/048481-2026/lots-paginated/0/100?isBeingPublished=false"]:
        r = pg.evaluate("async u => { const r = await fetch(u); return [r.status, await r.text()] }", api)
        print("\n#### START", api, r[0])
        try:
            j = json.loads(r[1]); print(json.dumps(corto(j), ensure_ascii=False)[:3500])
        except Exception:
            print(r[1][:800])
    pg.goto("https://intercenter.regione.emilia-romagna.it/trovabando/BANDO_GARA_PORTALE@17518962", wait_until="domcontentloaded", timeout=90000)
    api = pg.url.replace("intercenter.regione.emilia-romagna.it/", "intercenter.regione.emilia-romagna.it/++api++/", 1)
    r = pg.evaluate("async u => { const r = await fetch(u + '?expand=breadcrumbs'); return [r.status, await r.text()] }", api)
    print("\n#### INTERCENT", api, r[0])
    try:
        print(json.dumps(corto(json.loads(r[1])), ensure_ascii=False)[:5000])
    except Exception:
        print(r[1][:800])
    b.close()
