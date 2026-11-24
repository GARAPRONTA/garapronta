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
    ("TuttoGare", lambda u: "tuttogare" in u, r"/?allegati/open\.php\?[^\"'\s<>]+"),
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
    def prio(h):
        n = h.lower()
        try:
            q = parse_qs(urlparse(h).query)
            if "filename" in q:
                n += base64.b64decode(q["filename"][0]).decode("utf-8", "ignore").lower()
        except Exception:
            pass
        for i, k in enumerate(["disciplinar", "invito", "bando", "avviso", "criteri", "capitolat", "elenco", "computo"]):
            if k in n:
                return i
        return 20 if re.search(r"progett|elaborat|tavol|esecutiv|\.zip", n) else 10
    trovati.sort(key=prio)
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


import lettori


def _get(url, method="GET", data=None, headers=None):
    """get() per i lettori: sessione con cookie e referer, come un browser."""
    h = {"user-agent": UA, "accept-language": "it-IT,it;q=0.9",
         "accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*;q=0.8"}
    if _referer[0]:
        h["referer"] = _referer[0]
    h.update(headers or {})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    fine = time.time() + 90
    try:
        with opener.open(req, timeout=30) as r:
            buf = bytearray()
            while True:
                pezzo = r.read(256 * 1024)
                if not pezzo:
                    break
                buf += pezzo
                if len(buf) > MAX_FILE or time.time() > fine:
                    raise ValueError("file troppo grande o lento")
            hd = {k.lower(): v for k, v in r.headers.items()}
            if "text/html" in hd.get("content-type", ""):
                _referer[0] = r.geturl()
            return r.status, hd, bytes(buf), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b"", url


def browser_scarica(url):
    """Browser automatico: per pagine dinamiche (es. MEPA). Legge i link dopo il caricamento e,
    se non ce ne sono, clicca i documenti e cattura i download."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], []
    files, links = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(5000)
            for t in ("Documenti di gara", "Documentazione", "Documenti", "Allegati"):
                try:
                    pg.get_by_text(t, exact=True).first.click(timeout=2000)
                    pg.wait_for_timeout(2500)
                    break
                except Exception:
                    pass
            html = pg.content()
            for fr in pg.frames[1:]:
                try:
                    html += fr.content()
                except Exception:
                    pass
            links = lettori.link_file(html, pg.url)
            if not links:
                cand = pg.locator("text=/\\.(pdf|p7m|zip)\\s*$/i")
                for i in range(min(cand.count(), 10)):
                    try:
                        with pg.expect_download(timeout=15000) as dl:
                            cand.nth(i).click(timeout=5000)
                        d = dl.value
                        files.append((d.suggested_filename, open(d.path(), "rb").read()))
                    except Exception:
                        continue
        finally:
            b.close()
    return links, files


JS_START = lettori.JS_START


def browser_start(url):
    """START Toscana: apre la scheda con Chrome e scarica gli allegati pubblici cliccandoli, come un utente."""
    if not re.search(r"/tenders/[0-9]{6}-[0-9]{4}", url):
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    files = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(8000)
            cand = pg.locator("a").filter(has_text=re.compile(r"\.(pdf|p7m|zip|7z|docx?|odt|rtf)\s*$", re.I))
            nomi = []
            for i in range(min(cand.count(), 40)):
                t = cand.nth(i).inner_text().strip()
                if t and t not in [n for n, _ in nomi]:
                    nomi.append((t, i))
            nomi.sort(key=lambda x: lettori._prio(x[0]))
            t0 = time.time()
            for nome, i in nomi[:MAX_FILES]:
                if time.time() - t0 > 150:
                    break
                try:
                    with pg.expect_download(timeout=40000) as dl:
                        cand.nth(i).click(timeout=5000)
                    d = dl.value
                    files.append((d.suggested_filename or nome, open(d.path(), "rb").read()))
                except Exception:
                    continue
        finally:
            b.close()
    return files


def gara(cig, url, titolo=""):
    """Scarica i documenti di una gara. Restituisce (esito, metodo, files)."""
    metodo = "diretto"
    if "start.toscana.it" in url:
        fl = browser_start(url)
        return ("ok" if fl else "nessun file trovato"), "browser-start", fl
    try:
        elementi = lettori.trova(url, cig, titolo, _get)
    except PermissionError as e:
        return f"bloccata ({e})", metodo, []
    except Exception as e:
        return f"bloccata ({type(e).__name__})", metodo, []
    if not elementi:
        links, fl = browser_scarica(url)
        metodo = "browser"
        if fl:
            return "ok", metodo, fl[:MAX_FILES]
        elementi = [("url", x) for x in links]
    if not elementi:
        return "nessun file trovato", metodo, []
    files, t0 = [], time.time()
    for el in elementi:
        if len(files) >= MAX_FILES or time.time() - t0 > 150:
            break
        if el[0] == "file":
            files.append((el[1], el[2]))
            continue
        try:
            st, hd, data, _ = _get(el[1])
            if st != 200 or ("text/html" in hd.get("content-type", "") and data[:4] != b"%PDF"):
                continue
            files.append((nome_file(el[1], hd), data))
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


def una(url, cart, cig="", titolo=""):
    """Processo figlio: una sola pagina di gara, con tempo limitato dal processo padre."""
    global _proxy_url
    try:
        esito, metodo, files = gara(cig, url, titolo)
    except Exception as e:
        esito, metodo, files = f"errore {type(e).__name__}", "diretto", []
    nf = 0
    if files:
        docs = salva_gara(files, cart)
        nf = len(files)
        if not any(x["caratteri"] > 500 for x in docs):
            esito = "file senza testo (scansioni?)"
    print(json.dumps({"esito": esito, "metodo": metodo, "file": nf}))


ACTOR = "nIBsoLkrJU9zeelw0"   # garapronta-fetcher su Apify


def actor_id(tok, nome):
    j = json.load(urllib.request.urlopen(f"https://api.apify.com/v2/acts?token={tok}&my=true&limit=50", timeout=60))
    return next((a["id"] for a in j["data"]["items"] if a["name"] == nome), None)


def apify_scarica(tok, pagine, info=None, actor=ACTOR):
    """Lancia l'actor su Apify, aspetta (max 15 min) e scarica i file trovati. {pagina: [(nome, bytes)]}"""
    A = "https://api.apify.com/v2"
    req = urllib.request.Request(f"{A}/acts/{actor}/runs?token={tok}&memory=2048&timeout=1500",
                                 data=json.dumps({"pages": pagine, "info": info or {}}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    run = json.load(urllib.request.urlopen(req, timeout=60))["data"]
    fine = time.time() + 1560
    while run["status"] in ("READY", "RUNNING") and time.time() < fine:
        time.sleep(15)
        run = json.load(urllib.request.urlopen(f"{A}/actor-runs/{run['id']}?token={tok}", timeout=60))["data"]
    print(f"  run Apify {run['id']} {run['status']} {run.get('statusMessage') or ''} · costo {run.get('usageTotalUsd', 0):.3f} $", flush=True)
    items = json.load(urllib.request.urlopen(f"{A}/datasets/{run['defaultDatasetId']}/items?token={tok}&clean=1", timeout=60))
    out = {}
    for it in items:
        files = []
        for f in it.get("files") or []:
            try:
                data = urllib.request.urlopen(
                    f"{A}/key-value-stores/{run['defaultKeyValueStoreId']}/records/{f['key']}?token={tok}", timeout=120).read()
                files.append((f["nome"], data))
            except Exception:
                pass
        out[it["page"]] = files
        if not files:
            print(f"  {'apify':7} {it.get('esito', '?'):14} {urlparse(it['page']).netloc}", flush=True)
    return out


def lista(tsv, outdir):
    """Sul server: legge 'url\tcig\ttitolo' e stampa 'url\tjson' per ogni gara (3 alla volta)."""
    from concurrent.futures import ThreadPoolExecutor
    righe = [l.rstrip("\n").split("\t") + ["", ""] for l in open(tsv, encoding="utf-8") if l.strip()]

    def uno(r):
        url, cig, tit = r[0], r[1], r[2]
        try:
            p = subprocess.run([sys.executable, __file__, "--una", url, f"{outdir}/{cig}", cig, tit],
                               capture_output=True, text=True, timeout=200)
            ris = json.loads((p.stdout.strip().splitlines() or ["{}"])[-1] or "{}")
        except Exception:
            ris = {}
        print(url + "\t" + json.dumps(ris or {"esito": "troppo lenta", "metodo": "-", "file": 0}), flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(uno, righe))


def vps_giro(falliti, unici, titoli, base):
    """Manda le gare fallite al server italiano, le fa leggere lì e riporta indietro i testi."""
    host, d = os.environ["VPS_HOST"], os.path.dirname(os.path.abspath(__file__))
    ssh = ["sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20", f"root@{host}"]
    scp = ["sshpass", "-e", "scp", "-o", "StrictHostKeyChecking=no"]
    with open("/tmp/vps.tsv", "w", encoding="utf-8") as f:
        for u in falliti:
            t = titoli.get(unici[u], "").replace("\t", " ").replace("\n", " ")
            f.write(f"{u}\t{unici[u]}\t{t}\n")
    subprocess.run(scp + [f"{d}/lettori.py", f"{d}/documenti.py", "/tmp/vps.tsv", f"root@{host}:/opt/garapronta/"],
                   check=True, timeout=120)
    r = subprocess.run(ssh + ["cd /opt/garapronta && rm -rf /tmp/gp && mkdir -p /tmp/gp && "
                              "./venv/bin/python documenti.py --lista vps.tsv /tmp/gp"],
                       capture_output=True, text=True, timeout=3600)
    out = {}
    for l in r.stdout.splitlines():
        if "\t" in l:
            u, j = l.split("\t", 1)
            try:
                out[u] = json.loads(j)
            except Exception:
                pass
    ok = {u: x for u, x in out.items() if x.get("file", 0) > 0}
    if ok:
        os.makedirs(base, exist_ok=True)
        tar = subprocess.run(ssh + ["tar czf - -C /tmp/gp ."], capture_output=True, timeout=600).stdout
        subprocess.run(["tar", "xzf", "-", "-C", base], input=tar, check=True)
    return ok


def main():
    giorno = os.environ.get("DATA") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d/%m/%Y")
    d = datetime.strptime(giorno, "%d/%m/%Y")
    avvisi = json.load(gzip.open(f"data/{d:%Y/%m/%d}.json.gz", "rt"))
    righe, titoli = [], {}
    for a in avvisi:
        if a["tipo"] != "avviso" or a["tipologia"] not in ("BANDI", "INDAGINI_DI_MERCATO_SOTTO_SOGLIA"):
            continue
        for it in a["items"]:
            if (it.get("natura") or "").lower() == "lavori" and a.get("link") and it.get("cig"):
                righe.append((it["cig"], a["link"], a["tipologia"]))
                titoli[it["cig"]] = (a.get("titolo") or it.get("descr") or "")[:200]
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
            r = subprocess.run([sys.executable, __file__, "--una", url, f"{base}/{cig}", cig, titoli.get(cig, "")],
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
    DA_RIFARE = ("bloccata", "link senza file", "nessun file trovato", "troppo lenta", "errore", "file senza testo")
    # --- secondo giro: server italiano (Aruba) con Chrome, gratis
    falliti = [u for u, r in risultati.items() if r["esito"].split(" (")[0] in DA_RIFARE]
    if falliti and os.environ.get("VPS_HOST") and os.environ.get("SSHPASS"):
        print(f"\n== Server italiano: riprovo {len(falliti)} pagine", flush=True)
        try:
            for url, ris in vps_giro(falliti, unici, titoli, base).items():
                risultati[url] = {**ris, "metodo": "server-IT/" + ris.get("metodo", "")}
                print(f"  server  {ris['esito']:24} {ris['file']:2} file  {urlparse(url).netloc}", flush=True)
        except Exception as e:
            print(f"  Server italiano non disponibile: {e}", flush=True)
    # --- terzo giro: le pagine ancora fallite passano dal programma su Apify (proxy residenziale)
    tok = os.environ.get("APIFY_TOKEN")
    falliti = [u for u, r in risultati.items() if r["esito"].split(" (")[0] in DA_RIFARE]
    SOLO = ("traspare",)   # piattaforme dove il proxy Apify ha dato risultati
    falliti = [u for u in falliti if any(k in u for k in SOLO)]
    if tok and falliti:
        print(f"\n== Apify (proxy italiano): riprovo {len(falliti)} pagine", flush=True)
        try:
            for url, files in apify_scarica(tok, falliti, {u: [unici[u], titoli.get(unici[u], "")] for u in falliti}).items():
                if not files:
                    continue
                cig = unici[url]
                docs = salva_gara(files, f"{base}/{cig}")
                es = "ok" if any(x["caratteri"] > 500 for x in docs) else "file senza testo (scansioni?)"
                risultati[url] = {"esito": es, "metodo": "apify-IT", "file": len(files)}
                print(f"  apify ok {len(files):2} file  {urlparse(url).netloc}", flush=True)
        except Exception as e:
            print(f"  Apify non disponibile: {e}", flush=True)
        # --- terzo giro: Chrome vero su Apify con indirizzo italiano (START, MEPA, piattaforme difficili)
        ancora = [u for u in falliti if risultati[u]["esito"] != "ok"]
        if ancora and os.environ.get("APIFY_BROWSER") == "1":
            print(f"\n== Apify browser (Chrome + proxy italiano): riprovo {len(ancora)} pagine", flush=True)
            try:
                bid = actor_id(tok, "garapronta-browser")
                for url, files in apify_scarica(tok, ancora, None, bid).items():
                    if not files:
                        continue
                    cig = unici[url]
                    docs = salva_gara(files, f"{base}/{cig}")
                    es = "ok" if any(x["caratteri"] > 500 for x in docs) else "file senza testo (scansioni?)"
                    risultati[url] = {"esito": es, "metodo": "apify-browser", "file": len(files)}
                    print(f"  browser ok {len(files):2} file  {urlparse(url).netloc}", flush=True)
            except Exception as e:
                print(f"  Apify browser non disponibile: {e}", flush=True)
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
    if len(sys.argv) >= 4 and sys.argv[1] == "--una":
        una(sys.argv[2], sys.argv[3], *(sys.argv[4:6]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--lista":
        lista(sys.argv[2], sys.argv[3])
    else:
        main()
