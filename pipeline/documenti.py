#!/usr/bin/env python3
"""GaraPronta — scaricamento documenti di gara.

Per ogni gara di LAVORI (bandi e indagini di mercato) di un giorno:
  1. apre il link ai documenti pubblicato su ANAC;
  2. trova i file con il lettore della piattaforma (TuttoGare, Maggioli PortaleAppalti, Traspare)
     o con il lettore generico; se la pagina è dinamica usa un browser automatico (Playwright);
  3. se la piattaforma blocca i server di GitHub, ripete passando dal proxy italiano di Apify;
  4. scarica i file (pdf, p7m, zip, doc), ne estrae il testo e salva testi/AAAA/MM/GG/<CIG>/.
Solo documenti pubblici: niente login, niente CAPTCHA, richieste lente.

Variabili: DATA (gg/mm/aaaa, default ieri), APIFY_TOKEN (opzionale, per il proxy), MAX_GARE.
"""
import base64, gzip, io, json, os, re, subprocess, sys, tempfile, time, zipfile
import urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qs, unquote

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 GaraPronta"
MAX_FILE = 30 * 1024 * 1024
MAX_FILES = 15
MAX_TESTO = 600_000          # caratteri salvati per gara
EST = (".pdf", ".p7m", ".zip", ".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx")

PIATTAFORME = [  # (nome, test sul dominio/percorso, pattern dei link ai file)
    ("TuttoGare", lambda u: "tuttogare" in u, r"allegati/open\.php\?[^\"'\s<>]+"),
    ("Maggioli PortaleAppalti", lambda u: "portaleappalti" in u.lower() or "maggiolicloud" in u,
     r"[^\"'\s<>]*downloadDocumentoPubblico\.action[^\"'\s<>]*"),
    ("Traspare", lambda u: "traspare" in u, r"[^\"'\s<>]*fs_public_action\?do=download_document[^\"'\s<>]*"),
]

_proxy_url = None
SCADENZA = time.time() + 150   # tempo massimo per il browser nel processo di una gara
import threading
_browser_lock = threading.Lock()


def piattaforma(url):
    for nome, test, _ in PIATTAFORME:
        if test(url):
            return nome
    return urlparse(url).netloc


import http.cookiejar
_cookies = http.cookiejar.CookieJar()   # sessione della piattaforma (un processo = una gara)
_referer = [None]


def apri(url, proxy=False, max_bytes=MAX_FILE):
    h = {"user-agent": UA, "accept-language": "it-IT,it;q=0.9",
         "accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"}
    if _referer[0]:
        h["referer"] = _referer[0]
    handlers = [urllib.request.HTTPCookieProcessor(_cookies)]
    if proxy and _proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": _proxy_url, "https": _proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers=h)
    fine = time.time() + 90
    with opener.open(req, timeout=30) as r:
        buf = bytearray()
        while True:
            pezzo = r.read(256 * 1024)
            if not pezzo:
                break
            buf += pezzo
            if len(buf) > max_bytes:
                raise ValueError("file troppo grande")
            if time.time() > fine:
                raise TimeoutError("download troppo lento")
        return bytes(buf), r.headers, r.geturl()


def link_file(html, base, url_pagina):
    """Trova i link ai file nella pagina, con il lettore della piattaforma o quello generico."""
    html = unescape(html)
    trovati = []
    for nome, test, pat in PIATTAFORME:
        if test(url_pagina) or re.search(pat, html):
            trovati += re.findall(pat, html)
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.I):
        h = href.lower()
        if h.split("?")[0].endswith(EST) or re.search(r"(download|scarica|getfile|allegato|attachment)[^/]*([?=&]|$)", h):
            if not re.search(r"(login|registra|password|javascript:|mailto:|#$|verifica)", h):
                trovati.append(href)
    out, visti = [], set()
    for t in trovati:
        u = urljoin(base, t.strip())
        u = re.sub(r";jsessionid=[^?]+", "", u)
        if u not in visti and urlparse(u).scheme in ("http", "https"):
            visti.add(u)
            out.append(u)
    return out[:40]


def nome_file(url, headers):
    cd = headers.get("content-disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)', cd)
    if m:
        return unquote(m.group(1)).strip()
    q = parse_qs(urlparse(url).query)
    if "filename" in q:  # TuttoGare: base64
        try:
            return base64.b64decode(q["filename"][0]).decode("utf-8", "ignore")
        except Exception:
            pass
    return unquote(os.path.basename(urlparse(url).path)) or "documento"


def testo_da(nome, data):
    """Estrae il testo da pdf, p7m (firma digitale), zip, doc/docx."""
    n = nome.lower()
    if data[:2] == b"PK" and not n.endswith((".docx", ".xlsx", ".odt")):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for i in z.infolist()[:20]:
                if i.file_size < MAX_FILE:
                    out.append((i.filename, testo_da(i.filename, z.read(i))[1]))
        return "zip", "\n\n".join(f"### {f}\n{t}" for f, t in out if t)
    if n.endswith(".p7m") or data[:2] == b"\x30\x80" or (data[:1] == b"\x30" and b"PDF" not in data[:1024]):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
        r = subprocess.run(["openssl", "smime", "-verify", "-noverify", "-inform", "DER", "-in", f.name],
                           capture_output=True, timeout=60)
        os.unlink(f.name)
        if r.stdout:
            return testo_da(re.sub(r"\.p7m$", "", nome, flags=re.I), r.stdout)
        return "p7m", ""
    if data[:4] == b"%PDF":
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=120)
        os.unlink(f.name)
        return "pdf", r.stdout.decode("utf-8", "ignore")
    if n.endswith((".doc", ".docx", ".rtf", ".odt")):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, os.path.basename(nome) or "x.doc")
            open(p, "wb").write(data)
            subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text", "--outdir", d, p],
                           capture_output=True, timeout=180)
            t = [x for x in os.listdir(d) if x.endswith(".txt")]
            return "doc", open(os.path.join(d, t[0]), encoding="utf-8", errors="ignore").read() if t else ""
    return "altro", ""


TIPI = [("disciplinare", r"disciplinar"), ("lettera_invito", r"lettera.{0,5}invito|invito"),
        ("bando", r"bando"), ("avviso", r"avviso|manifestazion|indagine"), ("capitolato", r"capitolat|csa\b"),
        ("computo", r"computo|cme"), ("elenco_prezzi", r"elenco.{0,3}prezz"), ("dgue", r"dgue"),
        ("modulistica", r"modell|allegato|istanza|dichiaraz|modulo|offerta"), ("progetto", r"relazion|tavol|progett")]


def tipo_doc(nome):
    n = nome.lower()
    for t, p in TIPI:
        if re.search(p, n):
            return t
    return "altro"


PRIORITA = ["disciplinare", "lettera_invito", "bando", "avviso", "capitolato", "elenco_prezzi", "computo", "altro", "modulistica", "dgue", "progetto"]


def pagina_con_browser(url):
    """Browser automatico per le pagine dinamiche: restituisce l'HTML dopo il caricamento."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA, locale="it-IT")
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=20000)
            pg.wait_for_timeout(3000)
            html = pg.content()
            for fr in pg.frames[1:]:
                try:
                    html += fr.content()
                except Exception:
                    pass
            return html
        finally:
            b.close()


def gara(cig, url):
    """Scarica i documenti di una gara. Restituisce (esito, metodo, files)."""
    metodo, html, base = "diretto", None, url
    for tentativo in ("diretto", "proxy"):
        if tentativo == "proxy" and not _proxy_url:
            break
        try:
            data, hdr, base = apri(url, proxy=(tentativo == "proxy"), max_bytes=8_000_000)
            metodo = tentativo
            if data[:4] == b"%PDF" or "pdf" in (hdr.get("content-type") or ""):
                return "ok", metodo, [(nome_file(url, hdr), data)]
            html = data.decode("utf-8", "ignore")
            _referer[0] = base
            break
        except Exception as e:
            ultimo = f"{type(e).__name__}"
            continue
    if html is None:
        return f"bloccata ({ultimo})", metodo, []
    links = link_file(html, base, url)
    nota = any(test(url) for _, test, _ in PIATTAFORME)
    if not links and not nota and time.time() < SCADENZA:
        h2 = pagina_con_browser(url)
        if h2:
            links = link_file(h2, url, url)
            if links:
                metodo += "+browser"
    if not links:
        login = bool(re.search(r"login|accedi|spid|registrati", html, re.I))
        return ("serve accesso" if login and len(html) < 15000 else "nessun file trovato"), metodo, []
    files, t0 = [], time.time()
    for u in links[:MAX_FILES * 2]:
        if len(files) >= MAX_FILES or time.time() - t0 > 120:
            break
        try:
            data, hdr, _ = apri(u, proxy=("proxy" in metodo))
            ct = (hdr.get("content-type") or "").lower()
            if "text/html" in ct and data[:4] != b"%PDF":
                continue
            files.append((nome_file(u, hdr), data))
            time.sleep(0.5)
        except Exception:
            continue
    if not files and _proxy_url and "proxy" not in metodo:
        metodo += "+proxy-file"
        for u in links[:MAX_FILES * 2]:
            if len(files) >= MAX_FILES or time.time() - t0 > 200:
                break
            try:
                data, hdr, _ = apri(u, proxy=True)
                if "text/html" in (hdr.get("content-type") or "").lower() and data[:4] != b"%PDF":
                    continue
                files.append((nome_file(u, hdr), data))
            except Exception:
                continue
    return ("ok" if files else "link senza file"), metodo, files


def salva_gara(files, cart):
    """Estrae i testi e salva testi.json.gz nella cartella della gara. Restituisce l'elenco dei documenti."""
    os.makedirs(cart, exist_ok=True)
    docs = []
    for nome, data in files:
        try:
            formato, testo = testo_da(nome, data)
        except Exception:
            formato, testo = "errore", ""
        docs.append({"nome": nome[:150], "tipo": tipo_doc(nome), "formato": formato,
                     "kb": len(data) // 1024, "caratteri": len(testo), "testo": testo})
    docs.sort(key=lambda x: PRIORITA.index(x["tipo"]))
    budget, out = MAX_TESTO, []
    for x in docs:
        t = x.pop("testo")[: max(0, budget)]
        budget -= len(t)
        out.append({**x, "testo": t})
    with gzip.open(f"{cart}/testi.json.gz", "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return docs


def una(url, cart):
    """Processo figlio: una sola pagina di gara, con tempo limitato dal processo padre."""
    global _proxy_url
    tok = os.environ.get("APIFY_TOKEN")
    if tok:
        _proxy_url = f"http://groups-RESIDENTIAL,country-IT:{tok}@proxy.apify.com:8000"
    try:
        esito, metodo, files = gara(None, url)
    except Exception as e:
        esito, metodo, files = f"errore {type(e).__name__}", "diretto", []
    nf = 0
    if files:
        docs = salva_gara(files, cart)
        nf = len(files)
        if not any(x["caratteri"] > 500 for x in docs):
            esito = "file senza testo (scansioni?)"
    print(json.dumps({"esito": esito, "metodo": metodo, "file": nf}))


def main():
    giorno = os.environ.get("DATA") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d/%m/%Y")
    d = datetime.strptime(giorno, "%d/%m/%Y")
    avvisi = json.load(gzip.open(f"data/{d:%Y/%m/%d}.json.gz", "rt"))
    righe = []
    for a in avvisi:
        if a["tipo"] != "avviso" or a["tipologia"] not in ("BANDI", "INDAGINI_DI_MERCATO_SOTTO_SOGLIA"):
            continue
        for it in a["items"]:
            if (it.get("natura") or "").lower() == "lavori" and a.get("link") and it.get("cig"):
                righe.append((it["cig"], a["link"], a["tipologia"]))
                break
    righe = righe[: int(os.environ.get("MAX_GARE", "200"))]
    print(f"== {giorno}: {len(righe)} gare di lavori da leggere · proxy {'sì' if os.environ.get('APIFY_TOKEN') else 'no'}", flush=True)
    base = f"testi/{d:%Y/%m/%d}"
    unici = {}
    for cig, url, _ in righe:
        unici.setdefault(url, cig)
    from concurrent.futures import ThreadPoolExecutor
    fatte = [0]

    def lancia(item):
        url, cig = item
        t = time.time()
        try:
            r = subprocess.run([sys.executable, __file__, "--una", url, f"{base}/{cig}"],
                               capture_output=True, text=True, timeout=240)
            ris = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1] or "{}") or {"esito": "errore", "metodo": "-", "file": 0}
        except subprocess.TimeoutExpired:
            ris = {"esito": "troppo lenta", "metodo": "-", "file": 0}
        except Exception as e:
            ris = {"esito": f"errore {type(e).__name__}", "metodo": "-", "file": 0}
        fatte[0] += 1
        print(f"  [{fatte[0]:3}] {time.time() - t:4.0f}s {ris['esito']:24} {ris['file']:2} file  {urlparse(url).netloc}", flush=True)
        return url, ris
    with ThreadPoolExecutor(max_workers=8) as ex:
        risultati = dict(ex.map(lancia, unici.items()))
    esiti, per_piatt, rapporto = Counter(), {}, []
    for cig, url, tip in righe:
        r = risultati[url]
        p = piattaforma(url)
        e = r["esito"].split(" (")[0]
        esiti[e] += 1
        per_piatt.setdefault(p, Counter())[e] += 1
        rapporto.append({"cig": cig, "url": url, "piattaforma": p, **r})
    os.makedirs(base, exist_ok=True)
    json.dump(rapporto, open(f"{base}/rapporto.json", "w"), ensure_ascii=False, indent=1)
    ok = esiti.get("ok", 0)
    print(f"\nCOPERTURA: {ok}/{len(righe)} gare con documenti ({ok / max(1, len(righe)) * 100:.0f}%)")
    print("Esiti:", dict(esiti))
    for p, c in sorted(per_piatt.items(), key=lambda x: -sum(x[1].values()))[:20]:
        print(f"  {p:45} {dict(c)}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--una":
        una(sys.argv[2], sys.argv[3])
    else:
        main()
