"""Sul server italiano: recupera i prezzari 2026 delle regioni che li pubblicano tramite applicazioni web o portali
open data. Per ogni pagina clicca i pulsanti di download/esportazione (xml, xls, csv, ods) come farebbe una persona
e salva i file in /opt/garapronta/prezzari/<Regione>_<file>."""
import json, os, re, urllib.request
from playwright.sync_api import sync_playwright

D = "/opt/garapronta/prezzari"
os.makedirs(D, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
DATI = re.compile(r"\.(xml|xlsx?|ods|csv|zip)(\?|$|/)", re.I)
TESTO = re.compile(r"(xml|xls|excel|csv|ods|open ?data|formato aperto|scarica|download|esporta|export)", re.I)
NO = re.compile(r"(pdf|analisi|word|\.doc|202[0-5]|201\d|sicurezza covid)", re.I)

PAGINE = {
    "Veneto": ["https://www.regione.veneto.it/web/lavori-pubblici/prezzario-regionale"],
    "Toscana": ["https://prezzariollpp.regione.toscana.it/2026/firenze"],
    "Piemonte": ["https://prezzario.regione.piemonte.it/2026", "https://www.servizi.piemonte.it/srv/prezzario/"],
    "Campania": ["https://prezzario.regione.campania.it/"],
    "Sardegna": ["https://prezzario.regione.sardegna.it/prezzario/"],
    "Basilicata": ["https://prezzariooperepubbliche.regione.basilicata.it/prezzarioop/prezzario/prezzari.xhtml"],
    "Bolzano": ["https://prezzario.provincia.bz.it/"],
    "Trento": ["https://contrattipubblici.provincia.tn.it/Servizi/Elenco-Prezzi-P.A.T."],
    "Umbria": ["https://www.regione.umbria.it/opere-pubbliche/edizione-in-vigore"],
    "Molise": ["https://www.regione.molise.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/193"],
    "Liguria": ["https://appaltiliguria.regione.liguria.it/"],
    "Valle d'Aosta": ["https://www.regione.vda.it/operepubbliche/prezziario/elenco_prezzi_2026_i.aspx"],
    "Puglia": ["https://www.regione.puglia.it/web/territorio-mobilita-e-infrastrutture/elenco-prezzi-opere-pubbliche"],
    "Sicilia": ["https://www.regione.sicilia.it/istituzioni/regione/strutture-regionali/assessorato-infrastrutture-mobilita/dipartimento-regionale-tecnico/commissione-regionale-prezziario/prezziario-unico-regionale-per-lavori-pubblici/prezziario-vigente"],
    "Calabria": ["https://www.regione.calabria.it/edilizia-infrastrutture-difesa-del-suolo-e-mobilita/prezzario-regionale-oo-pp/"],
    "Lazio": ["https://www.regione.lazio.it/cittadini/lavori-pubblici-infrastrutture/tariffa-prezzi-lavori-pubblici"],
}
CKAN = {"Puglia": ("https://dati.puglia.it/ckan", "prezzario"), "Sicilia": ("https://dati.regione.sicilia.it", "prezzario")}


def salva(reg, nome, data):
    nome = re.sub(r"[^\w.\-]", "_", nome)[-80:]
    r_ = re.sub(r"[^\w.\-]", "_", reg)
    p = f"{D}/{r_}_{nome}"
    open(p, "wb").write(data)
    print(f"   SALVATO {os.path.basename(p)} · {len(data) // 1024} KB", flush=True)


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"user-agent": UA}), timeout=300).read()


# 1. portali open data (CKAN)
for reg, (base, q) in CKAN.items():
    print(f"\n## {reg} (open data)", flush=True)
    try:
        r = json.loads(get(f"{base}/api/3/action/package_search?q={q}&rows=20"))["result"]["results"]
        for p in r:
            for res in p.get("resources", []):
                u, t = res.get("url", ""), (res.get("name") or "") + " " + (p.get("title") or "")
                if "2026" in u + t and re.search(r"csv|xls|xml|ods|zip", (res.get("format") or "") + u, re.I):
                    print("   ", t[:80], u[:160], flush=True)
                    salva(reg, os.path.basename(u.split("?")[0]) or "prezzario.csv", get(u))
    except Exception as e:
        print("   errore", e)

# 2. pagine web e applicazioni: link diretti + clic sui pulsanti di esportazione
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for reg, urls in PAGINE.items():
        print(f"\n## {reg}", flush=True)
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True)
        pg = ctx.new_page()
        presi = 0
        for url in urls:
            try:
                pg.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as e:
                print("   apertura:", type(e).__name__, url[:90]); continue
            pg.wait_for_timeout(3000)
            for t in ("Accetta", "Accetto", "Accept", "OK", "Chiudi"):
                try:
                    pg.get_by_role("button", name=re.compile(t, re.I)).first.click(timeout=1500)
                except Exception:
                    pass
            els = pg.eval_on_selector_all("a, button, [role=button], input[type=button], input[type=submit]",
                "es => es.map((e, i) => [i, e.tagName, (e.innerText || e.value || e.title || e.getAttribute('aria-label') || '').trim().slice(0, 90), e.href || ''])")
            cand = [x for x in els if (DATI.search(x[3]) or TESTO.search(x[2] + " " + x[3])) and not NO.search(x[2] + " " + x[3])]
            print(f"   {len(cand)} candidati su {url[:70]}", flush=True)
            for i, tag, testo, href in cand[:12]:
                print("    -", tag, testo[:60].replace("\n", " "), "|", href[:120], flush=True)
            for i, tag, testo, href in cand[:12]:
                if presi >= 3:
                    break
                try:
                    if href and DATI.search(href):
                        salva(reg, os.path.basename(href.split("?")[0]), get(href)); presi += 1; continue
                    loc = pg.locator("a, button, [role=button], input[type=button], input[type=submit]").nth(i)
                    with pg.expect_download(timeout=90000) as dl:
                        loc.click(timeout=5000)
                    d = dl.value
                    if DATI.search(d.suggested_filename or ""):
                        salva(reg, d.suggested_filename, open(d.path(), "rb").read()); presi += 1
                except Exception:
                    continue
        ctx.close()
    b.close()
