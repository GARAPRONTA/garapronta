"""Diagnosi dei lettori: per ogni pagina di esempio salva l'HTML (diretto e dopo il caricamento in Chrome),
i link, i pulsanti e le richieste di rete, così si capisce dove stanno i documenti.
Uso: python tools/diag_pagine.py <cartella_uscita>   (le pagine sono fisse, in PAGINE)"""
import gzip, json, os, re, sys, time, urllib.request

PAGINE = {
    "sintel_ricerca": "https://www.sintel.regione.lombardia.it/eprocdata/sintelSearch.xhtml",
    "anas_jaggaer": "https://acquisti.stradeanas.it/esop/guest/go/opportunity/detail?opportunityId=26304",
    "acea_jaggaer": "https://procurement-gruppoacea.app.jaggaer.com/esop/guest/go/opportunity/detail?opportunityId=20436",
    "empulia_home": "http://www.empulia.it/tno-a/empulia/SitePages/Home.aspx",
    "albofornitori": "https://app.albofornitori.it/alboeproc/albo_ucomidrogeosicilia",
    "maggioli_bari": "https://portaleappalti.comune.bari.it/PortaleAppalti/it/procedure/codice/L26013",
    "maggioli_tivoli": "https://cuc-comunitamontanativoli.org/PortaleAppalti/it/procedure/codice/G00267",
    "fvg_eappalti": "https://eappalti.regione.fvg.it/",
    "fvgstrade": "https://www.fvgstrade.it/it/31103/gara-europea-a-procedura-aperta-gara-08-2026-friuli-venezia-giulia-strade-s-p-a-accordo-quadro-per-interve",
    "ted_808161": "https://ted.europa.eu/it/notice/808161-2026/xml",
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
