"""Diagnosi dei lettori: per ogni pagina di esempio salva l'HTML (diretto e dopo il caricamento in Chrome),
i link, i pulsanti e le richieste di rete, così si capisce dove stanno i documenti.
Uso: python tools/diag_pagine.py <cartella_uscita>   (le pagine sono fisse, in PAGINE)"""
import gzip, json, os, re, sys, time, urllib.request

PAGINE = {
    "tuttogare_frosinone": "https://comunefrosinone.tuttogare.it/gare/dettaglio.php?codice=217",
    "tuttogare_parma": "https://parmainfrastrutture.tuttogare.it/gare/dettaglio.php?codice=738",
    "tuttogare_sanpietro": "https://sanpietroamaida.tuttogare.it/gare/dettaglio.php?codice=59",
    "asmecomm_125795": "https://piattaforma.asmecomm.it/gare/dettaglio.php?codice=125795",
    "asmecomm_125392": "https://piattaforma.asmecomm.it/gare/dettaglio.php?codice=125392",
    "sardegnacat_1074228": "https://sardegnacat.regione.sardegna.it/Application/CustomDoc/DettaglioProcedura.asp?ID=1074228",
    "sardegnacat_1084883": "https://sardegnacat.regione.sardegna.it/Application/CustomDoc/DettaglioProcedura.asp?ID=1084883",
    "sintel_226856892": "https://www.sintel.regione.lombardia.it/eprocdata/auctionDetail.xhtml?id=226856892",
    "start_049760": "https://start.toscana.it/tendering/tenders/049760-2026/view/detail/1",
    "sicilia_8240": "https://appalti.regionesiciliana.lavoripubblici.sicilia.it/gare/dettaglio.php?codice=8240",
    "maggioli_como": "https://provinciacomo-appalti.maggiolicloud.it/PortaleAppalti/it/procedure/codice/G01790",
    "halleysac_658": "https://sac3.halleysac.it/c023060/eg0/EGBANDI.HBL?bando=658",
    "intercenter_18824580": "https://intercenter.regione.emilia-romagna.it/trovabando/BANDO_GARA_PORTALE@18824580",
    "trasparenza_peccioli": "https://peccioli.trasparenza-valutazione-merito.it/web/trasparenza/papca-g/-/papca/display/10621828",
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
OUT = sys.argv[1] if len(sys.argv) > 1 else "diag"
SOLO = set(sys.argv[2].split(",")) if len(sys.argv) > 2 and sys.argv[2] else None
os.makedirs(OUT, exist_ok=True)


def diretto(url):
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": UA, "accept-language": "it-IT"}), timeout=60)
        b = r.read(8_000_000)
        return {"status": r.status, "url_finale": r.geturl(), "byte": len(b), "secondi": round(time.time() - t, 1),
                "tipo": r.headers.get("content-type")}, b
    except Exception as e:
        return {"errore": f"{type(e).__name__}: {e}"[:300], "secondi": round(time.time() - t, 1)}, b""


def chrome(url):
    from playwright.sync_api import sync_playwright
    info, reti = {}, []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="it-IT")
        pg = ctx.new_page()
        pg.on("request", lambda r: reti.append(r.method + " " + r.url[:300]))
        t = time.time()
        try:
            pg.goto(url, wait_until="commit", timeout=90000)
            info["commit_s"] = round(time.time() - t, 1)
            for _ in range(12):
                pg.wait_for_timeout(5000)
                if pg.locator("a").count() > 15:
                    break
            info["attesa_s"] = round(time.time() - t, 1)
        except Exception as e:
            info["errore"] = f"{type(e).__name__}: {e}"[:300]
        try:
            html = pg.content()
            for fr in pg.frames[1:]:
                try:
                    html += "\n<!-- FRAME " + fr.url + " -->\n" + fr.content()
                except Exception:
                    pass
            info["url_finale"] = pg.url
            info["link"] = pg.eval_on_selector_all("a", "els => els.map(e => [e.innerText.trim().slice(0,120), e.getAttribute('href'), e.getAttribute('onclick')]).filter(x => x[0] || x[1])")[:400]
            info["pulsanti"] = pg.eval_on_selector_all("button, input[type=button], input[type=submit], [role=button], [role=tab]",
                                                      "els => els.map(e => (e.innerText || e.value || '').trim().slice(0,80)).filter(Boolean)")[:150]
        except Exception as e:
            html, info["errore2"] = "", f"{type(e).__name__}: {e}"[:300]
        b.close()
    info["rete"] = [x for x in reti if not re.search(r"\.(css|png|jpe?g|gif|svg|woff2?|ttf|ico)(\?|$)", x)][:300]
    return info, html.encode()


for nome, url in PAGINE.items():
    if SOLO and nome not in SOLO:
        continue
    print("==", nome, url, flush=True)
    d, b = diretto(url)
    print("   diretto:", {k: v for k, v in d.items()}, flush=True)
    open(f"{OUT}/{nome}.diretto.html.gz", "wb").write(gzip.compress(b))
    try:
        c, h = chrome(url)
    except Exception as e:
        c, h = {"errore": f"{type(e).__name__}: {e}"[:300]}, b""
    print("   chrome:", {k: v for k, v in c.items() if k not in ("link", "pulsanti", "rete")}, "link", len(c.get("link", [])), flush=True)
    open(f"{OUT}/{nome}.chrome.html.gz", "wb").write(gzip.compress(h))
    json.dump({"url": url, "diretto": d, "chrome": c}, open(f"{OUT}/{nome}.json", "w"), ensure_ascii=False, indent=1)
