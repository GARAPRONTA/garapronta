"""Sul server italiano: piattaforma prezzari 'apillppv2' (Toscana, Campania, Sardegna, Piemonte) e Veneto."""
import json, urllib.request
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
API = {"Toscana": "https://www308.regione.toscana.it/api/apillppv2-years-v2",
       "Campania": "https://gestione-prezzario.regione.campania.it/api/apillppv2-years-v2",
       "Sardegna": "https://prezzariogestione.regione.sardegna.it/api/apillppv2-years-v2",
       "Piemonte": "https://gestione-prezzario.regione.piemonte.it/api/apillppv2-years-v2"}
for reg, u in API.items():
    try:
        j = urllib.request.urlopen(urllib.request.Request(u, headers={"user-agent": UA}), timeout=60).read().decode()
        print(f"## {reg} anni:", j[:900])
    except Exception as e:
        print(reg, "ERR", e)
with sync_playwright() as p:
    b = p.chromium.launch()
    for reg, u in [("Toscana", "https://prezzariollpp.regione.toscana.it/2026/firenze"),
                   ("Campania", "https://prezzario.regione.campania.it/2026"),
                   ("Sardegna", "https://prezzario.regione.sardegna.it/2026"),
                   ("Veneto", "https://prezzario.regione.veneto.it/?anno=2026")]:
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True)
        pg = ctx.new_page(); req = []
        pg.on("request", lambda r: req.append(r.method + " " + r.url[:200]) if r.resource_type in ("xhr", "fetch", "document") else None)
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(reg, "goto", e)
        pg.wait_for_timeout(3000)
        print(f"\n## {reg} {pg.url} · {pg.title()}")
        print("   testo:", pg.inner_text("body")[:400].replace("\n", " | "))
        n0 = len(req)
        try:
            pg.get_by_text("SCARICA", exact=False).first.click(timeout=5000)
            pg.wait_for_timeout(3000)
            print("   dopo SCARICA:", pg.inner_text("body")[:600].replace("\n", " | "))
            for t in ("XML", "Xml", "CSV", "Excel", "XLS"):
                try:
                    with pg.expect_download(timeout=60000) as dl:
                        pg.get_by_text(t, exact=False).first.click(timeout=4000)
                    print("   DOWNLOAD", t, dl.value.suggested_filename, dl.value.url[:200]); break
                except Exception as e:
                    print("   no", t, type(e).__name__)
        except Exception as e:
            print("   SCARICA non trovato", type(e).__name__)
        print("   richieste:", req[n0:n0 + 15])
        ctx.close()
    b.close()
