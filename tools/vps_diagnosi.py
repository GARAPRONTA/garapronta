"""Diagnosi sul server italiano: come la consultazione pubblica dei programmi triennali (MIT SCP) carica i dati."""
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(user_agent=UA, locale="it-IT")
    reqs = []
    pg.on("response", lambda r: reqs.append((r.status, r.request.method, r.url[:220])) if r.request.resource_type in ("xhr", "fetch", "document") else None)
    for url in ["https://www.serviziocontrattipubblici.it/it/consultazione/",
                "https://www.serviziocontrattipubblici.it/scpprogrammi-fe/"]:
        print("\n=====", url, flush=True)
        try:
            pg.goto(url, wait_until="networkidle", timeout=90000)
        except Exception as e:
            print("ERR", e)
        print("title:", pg.title(), pg.url)
        print("link:", [(a.inner_text().strip()[:50], a.get_attribute("href")) for a in pg.locator("a").all()[:80] if a.get_attribute("href") and ("program" in (a.get_attribute("href") or "").lower() or "consult" in (a.get_attribute("href") or "").lower())])
        print("testo:", pg.inner_text("body")[:1500].replace("\n", " | "))
    for t in ("Programmazione", "Programmi", "Ricerca", "Cerca"):
        try:
            pg.get_by_text(t).first.click(timeout=4000); pg.wait_for_timeout(6000); print("cliccato", t, pg.url); break
        except Exception:
            pass
    print("testo dopo:", pg.inner_text("body")[:1500].replace("\n", " | "))
    for s, m, u in reqs:
        print("  ", s, m, u)
    b.close()
