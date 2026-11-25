"""Sul server italiano: scarica i prezzari in vigore delle regioni con piattaforme web (2° giro)."""
import os, re, subprocess
from playwright.sync_api import sync_playwright

D = "/opt/garapronta/prezzari"; os.makedirs(D, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def prova(reg, urls):
    for u in urls:
        dest = f"{D}/{reg}_" + re.sub(r"[^\w.\-]", "_", os.path.basename(u.split("?")[0]))
        r = subprocess.run(["curl", "-fsSL", "-A", UA, "-o", dest, u], timeout=900)
        if r.returncode == 0 and os.path.getsize(dest) > 10000:
            print(f"   {reg}: SALVATO {os.path.basename(dest)} · {os.path.getsize(dest) // 1024} KB", flush=True)
            return True
        if os.path.exists(dest):
            os.remove(dest)
    print(f"   {reg}: nessun file tra {len(urls)} tentativi", flush=True)
    return False


# piattaforma comune: /data/<anno>-<edizione>/<file>
prova("Campania", ["https://gestione-prezzario.regione.campania.it/data/2026-0/2026_(XML).zip"])
prova("Piemonte", ["https://gestione-prezzario.regione.piemonte.it/data/2026-1/2026_1_XML.zip"])
prova("Sardegna", [f"https://prezzariogestione.regione.sardegna.it/data/{e}/{f}" for e in ("2026-0", "2026-1", "2026")
                   for f in ("2026_(XML).zip", "2026_XML.zip", "2026_0_XML.zip", "2026_1_XML.zip")])
# prezzari ancora in vigore di anni precedenti (proroghe)
prova("Lazio", ["https://www.regione.lazio.it/sites/default/files/2023-05/Tariffa_2023_formato_open_DATA%20%281%29.zip"])

# applicazioni da usare con il browser, come farebbe una persona: Sardegna, Toscana, Veneto
with sync_playwright() as p:
    b = p.chromium.launch()
    for reg, u, passi in [
        ("Sardegna", "https://prezzario.regione.sardegna.it/2026", ["XML", "Xml", "CSV", "XLS"]),
        ("Toscana", "https://prezzariollpp.regione.toscana.it/2026/firenze", ["SCARICA", "XML", "Xml", "CSV"]),
        ("Veneto", "https://prezzario.regione.veneto.it/?anno=2026", ["Esporta", "XML", "Xml", "Excel", "CSV", "ODS"]),
    ]:
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True, viewport={"width": 1400, "height": 900})
        pg = ctx.new_page()
        try:
            pg.goto(u, wait_until="networkidle", timeout=60000)
        except Exception:
            pass
        pg.wait_for_timeout(3000)
        preso = False
        for t in passi:
            loc = pg.locator(f"text=/{t}/").first
            try:
                with pg.expect_download(timeout=120000) as dl:
                    loc.click(timeout=5000)
                d = dl.value
                dest = f"{D}/{reg}_" + re.sub(r"[^\w.\-]", "_", d.suggested_filename)
                d.save_as(dest)
                print(f"   {reg}: SALVATO {os.path.basename(dest)} · {os.path.getsize(dest) // 1024} KB · {d.url[:150]}", flush=True)
                preso = True
                break
            except Exception as e:
                print(f"   {reg}: clic '{t}' senza download ({type(e).__name__})", flush=True)
                pg.wait_for_timeout(1500)
        if not preso:
            print(f"   {reg}: testo dopo i clic:", pg.inner_text("body")[:500].replace("\n", " | "))
        ctx.close()
    b.close()
