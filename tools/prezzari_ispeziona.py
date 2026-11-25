"""Sul server italiano: come si esporta l'intero prezzario da Toscana e Veneto, e cosa offrono le regioni piccole."""
import re
from playwright.sync_api import sync_playwright
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch()
    # Toscana: pulsante SCARICA
    ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True, viewport={"width": 1400, "height": 900})
    pg = ctx.new_page(); req = []
    pg.on("request", lambda r: req.append(r.method + " " + r.url[:220]) if r.resource_type in ("xhr", "fetch", "document") else None)
    pg.goto("https://prezzariollpp.regione.toscana.it/2026/firenze", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(3000)
    bt = pg.locator("button, a, [role=button]").filter(has_text=re.compile("scarica", re.I))
    print("## Toscana pulsanti SCARICA:", bt.count())
    n0 = len(req)
    try:
        bt.first.scroll_into_view_if_needed(); bt.first.click(timeout=8000, force=True); pg.wait_for_timeout(4000)
        print("   dopo clic:", pg.inner_text("body")[:900].replace("\n", " | "))
        print("   opzioni:", pg.eval_on_selector_all("button, a, [role=menuitem], li, mat-option", "es => es.map(e => (e.innerText||'').trim()).filter(t => t && t.length < 40)")[:60])
    except Exception as e:
        print("   clic fallito", e)
    print("   richieste:", req[n0:n0 + 10]); ctx.close()
    # Veneto: Esporta
    ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True, viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    pg.goto("https://prezzario.regione.veneto.it/?anno=2026", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(3000)
    try:
        pg.get_by_text("Esporta", exact=True).first.click(timeout=8000); pg.wait_for_timeout(4000)
        print("\n## Veneto dopo Esporta:", pg.url, pg.inner_text("body")[:1500].replace("\n", " | "))
        print("   form:", pg.eval_on_selector_all("select, input, button, a", "es => es.map(e => [e.tagName, e.name||'', (e.innerText||e.value||'').trim().slice(0,40), e.href||''])")[:80])
    except Exception as e:
        print("Veneto", e)
    ctx.close()
    # regioni piccole: tutti i link utili
    for reg, u in [("Umbria", "https://www.regione.umbria.it/opere-pubbliche/edizione-in-vigore"),
                   ("Valle d'Aosta", "https://www.regione.vda.it/operepubbliche/prezziario/elenco_prezzi_2026_i.aspx"),
                   ("Trento", "https://contrattipubblici.provincia.tn.it/Servizi/Elenco-Prezzi-P.A.T."),
                   ("Bolzano", "https://prezzario.provincia.bz.it/"),
                   ("Molise", "https://www.regione.molise.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/193"),
                   ("Basilicata", "https://prezzariooperepubbliche.regione.basilicata.it/prezzarioop/prezzario/prezzari.xhtml"),
                   ("Liguria", "https://appaltiliguria.regione.liguria.it/")]:
        pg = b.new_page(user_agent=UA, locale="it-IT")
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(2500)
        except Exception as e:
            print(reg, "goto", type(e).__name__)
        links = pg.eval_on_selector_all("a", "as => as.map(a => [(a.innerText||a.title||'').trim().replace(/\\s+/g,' ').slice(0,70), a.href])")
        print(f"\n## {reg} · {pg.title()[:60]}")
        for t, h in links:
            if re.search(r"2026|xls|xml|csv|ods|zip|excel|allegato|download|scarica|prezz|elenco", t + h, re.I) and not re.search(r"facebook|twitter|instagram|youtube|linkedin", h):
                print("    ", t, "|", h[:170])
        pg.close()
    b.close()
