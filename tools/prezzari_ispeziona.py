"""Sul server italiano: cosa mostrano le pagine dei prezzari che non hanno dato file."""
import re
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
P = {
 "Veneto": "https://www.regione.veneto.it/web/lavori-pubblici/prezzario-regionale",
 "Toscana": "https://prezzariollpp.regione.toscana.it/2026/firenze",
 "Campania": "https://prezzario.regione.campania.it/",
 "Sardegna": "https://prezzario.regione.sardegna.it/prezzario/",
 "Lazio": "https://www.regione.lazio.it/cittadini/lavori-pubblici-infrastrutture/tariffa-prezzi-lavori-pubblici",
 "Sicilia": "https://www.regione.sicilia.it/istituzioni/regione/strutture-regionali/assessorato-infrastrutture-mobilita/dipartimento-regionale-tecnico/commissione-regionale-prezziario/prezziario-unico-regionale-per-lavori-pubblici/prezziario-vigente",
 "Piemonte": "https://prezzario.regione.piemonte.it/2026",
 "Calabria": "https://www.regione.calabria.it/edilizia-infrastrutture-difesa-del-suolo-e-mobilita/prezzario-regionale-oo-pp/",
}
with sync_playwright() as p:
    b = p.chromium.launch()
    for reg, u in P.items():
        pg = b.new_page(user_agent=UA, locale="it-IT")
        xhr = []
        pg.on("response", lambda r: xhr.append((r.status, r.url[:150])) if r.request.resource_type in ("xhr", "fetch") else None)
        try:
            r = pg.goto(u, wait_until="networkidle", timeout=60000); st = r.status if r else None
        except Exception as e:
            st = type(e).__name__
        pg.wait_for_timeout(4000)
        print(f"\n## {reg} · {st} · {pg.title()[:80]}")
        try:
            print("   testo:", pg.inner_text("body")[:700].replace("\n", " | "))
        except Exception:
            pass
        links = pg.eval_on_selector_all("a", "as => as.map(a => [(a.innerText||'').trim().slice(0,60), a.href])")
        print("   link con 2026/xml/xls/ods/csv:")
        for t, h in links:
            if re.search(r"2026|xml|xls|ods|csv|zip|download|scarica", t + h, re.I):
                print("     ", t.replace("\n", " "), "|", h[:170])
        print("   xhr:", xhr[:12])
        pg.close()
    b.close()
