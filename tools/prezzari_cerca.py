"""Sul server italiano: esplora le pagine ufficiali dei prezzari regionali e trova i file in formato aperto."""
import json, re
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
PAGINE = {
    "Abruzzo": "https://www.regione.abruzzo.it/argomenti/lavori-pubblici/prezzario-regionale/prezzario-regionale-vigente",
    "Basilicata": "https://prezzariooperepubbliche.regione.basilicata.it/prezzarioop/prezzario/prezzari.xhtml",
    "Bolzano": "https://prezzario.provincia.bz.it/",
    "Calabria": "https://www.regione.calabria.it/edilizia-infrastrutture-difesa-del-suolo-e-mobilita/prezzario-regionale-oo-pp/",
    "Campania": "https://prezzario.regione.campania.it/",
    "Emilia-Romagna": "https://territorio.regione.emilia-romagna.it/osservatorio/elenco_regionale_prezzi",
    "Friuli-Venezia Giulia": "https://www.regione.fvg.it/rafvg/cms/RAFVG/infrastrutture-lavori-pubblici/lavori-pubblici/FOGLIA7/",
    "Lazio": "https://www.regione.lazio.it/cittadini/lavori-pubblici-infrastrutture/tariffa-prezzi-lavori-pubblici",
    "Liguria": "https://appaltiliguria.regione.liguria.it/",
    "Lombardia": "https://www.regione.lombardia.it/infrastrutture-trasporti-e-mobilita/opere-pubbliche/prezzario-regionale-dei-lavori-pubblici/ser-prezzario-infr",
    "Marche": "https://www.regione.marche.it/Regione-Utile/Edilizia-e-Lavori-Pubblici/Prezzario-regionale-lavori-pubblici",
    "Molise": "https://www.regione.molise.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/193",
    "Piemonte": "https://www.regione.piemonte.it/web/temi/protezione-civile-difesa-suolo-opere-pubbliche/opere-pubbliche/prezzario-regione-piemonte-2026",
    "Puglia": "https://www.regione.puglia.it/web/territorio-mobilita-e-infrastrutture/elenco-prezzi-opere-pubbliche",
    "Sardegna": "https://prezzario.regione.sardegna.it/prezzario/",
    "Sicilia": "https://www.regione.sicilia.it/istituzioni/regione/strutture-regionali/assessorato-infrastrutture-mobilita/dipartimento-regionale-tecnico/commissione-regionale-prezziario/prezziario-unico-regionale-per-lavori-pubblici/prezziario-vigente",
    "Toscana": "https://prezzariollpp.regione.toscana.it/",
    "Trento": "https://contrattipubblici.provincia.tn.it/Servizi/Elenco-Prezzi-P.A.T.",
    "Umbria": "https://www.regione.umbria.it/opere-pubbliche/edizione-in-vigore",
    "Valle d'Aosta": "https://www.regione.vda.it/operepubbliche/prezziario/elenco_prezzi_2026_i.aspx",
    "Veneto": "https://www.regione.veneto.it/web/lavori-pubblici/prezzario-regionale",
}
EST = re.compile(r"\.(xml|xlsx?|ods|csv|zip|json|xpwe|dcf|six)(\?|$)", re.I)
SEGUI = re.compile(r"(2026|prezz|open.?data|elenco.?prezzi|download|scarica|formato|tariff)", re.I)
risultati = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(user_agent=UA, locale="it-IT")
    for reg, url in PAGINE.items():
        pg = ctx.new_page()
        trovati, visti = [], set()
        coda = [(url, 0)]
        while coda and len(visti) < 10:
            u, d = coda.pop(0)
            if u in visti:
                continue
            visti.add(u)
            try:
                pg.goto(u, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(2500)
                links = pg.eval_on_selector_all("a[href]", "as => as.map(a => [a.href, (a.innerText||'').trim().slice(0,80)])")
            except Exception as e:
                print(f"  {reg}: errore {type(e).__name__} su {u[:90]}", flush=True)
                continue
            for h, t in links:
                if EST.search(h) or re.search(r"(xml|excel|xls|ods|csv|open ?data)", t, re.I):
                    if h not in [x[0] for x in trovati]:
                        trovati.append((h, t))
                elif d < 1 and SEGUI.search(h + " " + t) and urlparse(h).netloc == urlparse(url).netloc:
                    coda.append((h, d + 1))
        pg.close()
        risultati[reg] = trovati[:25]
        print(f"\n## {reg} ({len(trovati)} file, {len(visti)} pagine)", flush=True)
        for h, t in trovati[:25]:
            print("   ", t[:60].replace("\n", " "), "|", h[:200])
    b.close()
json.dump(risultati, open("/opt/garapronta/prezzari_link.json", "w"), ensure_ascii=False, indent=1)
