"""Diagnosi sul server italiano: chiamate della scheda documenti di START e struttura allegati Intercent-ER."""
import json
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(user_agent=UA, locale="it-IT")
    reqs = []
    pg.on("response", lambda r: reqs.append((r.status, r.request.resource_type, r.url[:200])) if r.request.resource_type in ("xhr", "fetch") else None)
    pg.goto("https://start.toscana.it/tendering/tenders/048481-2026/view/detail/1", wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_timeout(8000)
    print("TAB/LINK:", [t.strip()[:40] for t in pg.locator("a, button, [role=tab], li").all_inner_texts() if t.strip()][:80])
    n0 = len(reqs)
    for t in ("Documentazione", "Documenti", "Allegati", "Documentazione di gara", "Atti"):
        try:
            pg.get_by_text(t).first.click(timeout=3000); pg.wait_for_timeout(5000)
            print("cliccato:", t, "->", pg.url); break
        except Exception:
            pass
    for s, ty, u in reqs[n0:]:
        print("  ", s, u)
    for fr in pg.frames:
        try:
            body = fr.inner_text("body")
            if ".pdf" in body.lower() or ".p7m" in body.lower():
                print("FRAME con file:", fr.url[:120], body[:1200].replace("\n", " | "))
        except Exception:
            pass
    pg.goto("https://intercenter.regione.emilia-romagna.it/trovabando/BANDO_GARA_PORTALE@17518962", wait_until="domcontentloaded", timeout=90000)
    api = pg.url.replace("emilia-romagna.it/", "emilia-romagna.it/++api++/", 1)
    j = json.loads(pg.evaluate("async u => (await fetch(u)).text()", api))
    d = j["@components"]["intercenter-data"]["data"]
    print("\nINTERCENT allegati:", json.dumps(d["allegati"][:3], ensure_ascii=False)[:2500])
    print("links:", json.dumps(d["links"], ensure_ascii=False)[:600])
    b.close()
