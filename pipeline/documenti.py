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
import shutil, base64, gzip, io, json, os, re, subprocess, sys, tempfile, time, zipfile
import urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qs, unquote

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 GaraPronta"
MAX_FILE = 100 * 1024 * 1024   # singolo documento
MAX_ARCH = 300 * 1024 * 1024   # archivi di progetto (anche annidati: zip dentro zip)
MAX_FILES = 15
MAX_TESTO = 900_000          # caratteri salvati per gara
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



OCR_PAGINE = 25          # pagine massime lette con l'OCR per ogni PDF scansionato


def ocr_pdf(percorso):
    """Legge un PDF scansionato con Tesseract (italiano): immagini a 200 dpi delle prime OCR_PAGINE pagine."""
    if not shutil.which("tesseract"):
        return ""
    out = []
    with tempfile.TemporaryDirectory() as d:
        try:
            subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(OCR_PAGINE), "-png", percorso, f"{d}/p"],
                           capture_output=True, timeout=240)
            t0 = time.time()
            for img in sorted(os.listdir(d)):
                if time.time() - t0 > 150:
                    break
                r = subprocess.run(["tesseract", f"{d}/{img}", "-", "-l", "ita+eng", "--psm", "3"],
                                   capture_output=True, timeout=60)
                out.append(r.stdout.decode("utf-8", "ignore"))
        except Exception:
            pass
    return "\n\f".join(out)


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
        testo = r.stdout.decode("utf-8", "ignore")
        if len(testo.strip()) < 300 and tipo_doc(nome) not in ("progetto", "altro", "modulistica"):
            testo = ocr_pdf(f.name) or testo      # PDF scansionato: lo leggo con l'OCR
        os.unlink(f.name)
        return "pdf", testo
    if data[:2] == b"PK" and n.endswith((".docx", ".odt")):     # Word/OpenOffice: il testo sta in un XML dentro lo ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml" if n.endswith(".docx") else "content.xml").decode("utf-8", "ignore")
            xml = re.sub(r"</w:p>|</text:p>|</text:h>|<w:br/>|<w:tab/>", "\n", xml)
            t = unescape(re.sub(r"<[^>]+>", "", xml))
            if t.strip():
                return "doc", re.sub(r"\n{3,}", "\n\n", t)
        except Exception:
            pass
    if n.endswith(".rtf") and data[:5] == b"{\\rtf":
        t = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "ignore"), data.decode("latin-1", "ignore"))
        t = re.sub(r"\\par[d]?|\\line", "\n", t)
        t = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", t)
        if len(t.strip()) > 100:
            return "doc", t
    if n.endswith((".doc", ".docx", ".rtf", ".odt")):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, os.path.basename(nome) or "x.doc")
            open(p, "wb").write(data)
            subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text", "--outdir", d, p],
                           capture_output=True, timeout=180)
            t = [x for x in os.listdir(d) if x.endswith(".txt")]
            return "doc", open(os.path.join(d, t[0]), encoding="utf-8", errors="ignore").read() if t else ""
    return "altro", ""


TIPI = [("relazione", r"relazione[\s_.-]*(tecnic|illustrativ|descrittiv|generale(?![\s_.-]*di[\s_.-]*calcol))|quadro esigenziale|\bdip\b|documento.{0,4}indirizzo"),
        ("disciplinare", r"disciplinar"), ("lettera_invito", r"lettera.{0,5}invito|invito"),
        ("bando", r"bando"), ("avviso", r"avviso|manifestazion|indagine"), ("capitolato", r"capitolat|csa\b"),
        ("computo", r"computo|\bcme\b|metrico.?estim|stima.?lavori"), ("elenco_prezzi", r"elenco.{0,3}prezz"), ("dgue", r"dgue"),
        ("modulistica", r"modell|allegato|istanza|dichiaraz|modulo|offerta"), ("progetto", r"relazion|tavol|progett")]


def tipo_doc(nome):
    n = os.path.basename(nome).lower()
    for t, p in TIPI:
        if re.search(p, n):
            return t
    return "altro"


PRIORITA = ["disciplinare", "lettera_invito", "bando", "avviso", "relazione", "capitolato", "elenco_prezzi", "computo", "altro", "modulistica", "dgue", "progetto"]


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


COOKIE_NO = ("Solo cookies tecnici", "Solo cookie tecnici", "Rifiuta", "Rifiuta tutti", "Rifiuto", "Accetta solo necessari",
             "Solo necessari", "Accetto i cookie", "Ho capito", "OK")   # prima le scelte più riservate
CLICCABILI = ("a, label, span, button, td, li, div[onclick], [data-chiave-allegato]")
EST_RE = re.compile(r"\.(pdf|p7m|zip|7z|rar|docx?|odt|rtf)\s*(\(.*\))?\s*$", re.I)


def browser_scarica(url):
    """Browser automatico, come una persona: apre la pagina (segue i reindirizzamenti), chiude l'avviso cookie
    con la scelta più riservata, apre la sezione documenti, poi scarica gli allegati pubblici.
    Prima prova i link veri (con i cookie della stessa visita), poi clicca le voci che hanno nome di file
    (piattaforme JSF come Sintel, window.open come Liferay e SardegnaCAT) e cattura download o finestre."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [], []
    files = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="it-IT", accept_downloads=True)
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(6):
                pg.wait_for_timeout(2500)
                if pg.locator("a").count() > 15:
                    break
            for t in COOKIE_NO:
                try:
                    pg.get_by_role("button", name=t, exact=True).first.click(timeout=800)
                    break
                except Exception:
                    pass
            for t in ("Documenti di gara", "Documentazione di gara", "Documentazione", "Documenti", "Allegati", "Atti di gara"):
                try:
                    pg.get_by_text(t, exact=True).first.click(timeout=1500)
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
            # 1) link veri, scaricati dentro la stessa visita (stessi cookie: TuttoGare, Asmecomm, Maggioli)
            t0 = time.time()
            for u in links:
                if len(files) >= MAX_FILES or time.time() - t0 > 120:
                    break
                try:
                    r = ctx.request.get(u, timeout=60000, headers={"referer": pg.url})
                    body = r.body()
                    ct = r.headers.get("content-type", "")
                    if r.ok and body and len(body) < MAX_FILE and ("text/html" not in ct or body[:4] == b"%PDF"):
                        files.append((nome_file(u, {k.lower(): v for k, v in r.headers.items()}), body))
                except Exception:
                    continue
            # 2) voci con nome di file ma senza link vero: si cliccano
            if not files:
                cand = pg.locator(CLICCABILI).filter(has_text=EST_RE)
                visti, n = set(), 0
                for i in range(min(cand.count(), 120)):
                    if n >= MAX_FILES or time.time() - t0 > 170:
                        break
                    el = cand.nth(i)
                    try:
                        testo = el.inner_text(timeout=1000).strip()
                    except Exception:
                        continue
                    if not EST_RE.search(testo) or len(testo) > 200 or testo in visti or "\n" in testo.strip():
                        continue
                    visti.add(testo)
                    try:
                        with pg.expect_download(timeout=20000) as dl:
                            el.click(timeout=4000)
                        d = dl.value
                        files.append((d.suggested_filename or testo, open(d.path(), "rb").read()))
                        n += 1
                        continue
                    except Exception:
                        pass
                    # window.open: il file si apre in una nuova scheda
                    try:
                        nuove = [x for x in ctx.pages if x is not pg]
                        if nuove:
                            u = nuove[-1].url
                            for x in nuove:
                                x.close()
                            if u.startswith("http"):
                                r = ctx.request.get(u, timeout=60000, headers={"referer": pg.url})
                                if r.ok and r.body():
                                    files.append((testo, r.body()))
                                    n += 1
                    except Exception:
                        pass
        except Exception:
            links = []
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
            pg.goto(url, wait_until="domcontentloaded", timeout=120000)
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
                if time.time() - t0 > 170:
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
        try:
            fl = [(e[1], e[2]) for e in lettori.start_toscana(url, _get) if e[0] == "file"]
        except Exception:
            fl = []
        if fl:
            return "ok", "api-start", fl
        fl = browser_start(url)
        return ("ok" if fl else "nessun file trovato"), "browser-start", fl
    try:
        elementi = lettori.trova(url, cig, titolo, _get)
    except lettori.Riservata:
        return "documenti riservati agli invitati", metodo, []
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
    if not files and metodo == "diretto":     # i link c'erano ma non danno file: riprovo come una persona, nel browser
        _, fl = browser_scarica(url)
        if fl:
            return "ok", "browser", fl[:MAX_FILES]
    return ("ok" if files else "link senza file"), metodo, files


UTILI = (".pdf", ".p7m", ".doc", ".docx", ".rtf", ".odt", ".zip", ".7z", ".rar")
# negli archivi di progetto: niente tavole grafiche (lente da leggere e inutili per il resoconto)
GRAFICI = re.compile(r"(^|[\W_])(tav|tavola|planimetri|pianta|piante|sezion|prospett|particolar|grafic|render|foto|dwg|layout|schema)", re.I)


def _utile(nome):
    b = os.path.basename(nome)
    return b.lower().endswith(UTILI) and (not GRAFICI.search(b) or re.search(r"comput|prezz|stima|capitolat|relazion", b, re.I))


def espandi(files, livello=0):
    """Apre gli archivi (zip, 7z, rar) e restituisce i singoli documenti, con il nome 'archivio/percorso/file'.
    Così computo metrico, elenco prezzi e stima manodopera dentro lo ZIP del progetto vengono riconosciuti."""
    out = []
    for nome, data in files:
        n = nome.lower()
        arch = None
        if data[:2] == b"PK" and not n.endswith((".docx", ".xlsx", ".odt", ".ods")):
            arch = "zip"
        elif data[:6] == b"7z\xbc\xaf\x27\x1c" or n.endswith(".7z"):
            arch = "7z"
        elif data[:4] == b"Rar!" or n.endswith(".rar"):
            arch = "rar"
        if not arch or livello > 2:
            out.append((nome, data))
            continue
        interni = []
        try:
            if arch == "zip":
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for i in z.infolist()[:200]:
                        lim = MAX_ARCH if i.filename.lower().endswith((".zip", ".7z", ".rar")) else MAX_FILE
                        if not i.is_dir() and i.file_size < lim and _utile(i.filename) and len(interni) < 40:
                            interni.append((i.filename, z.read(i)))
            else:
                with tempfile.TemporaryDirectory() as d:
                    a = os.path.join(d, "a." + arch)
                    open(a, "wb").write(data)
                    subprocess.run(["7z", "x", "-y", f"-o{d}/x", a], capture_output=True, timeout=300)
                    for root, _, fs in os.walk(f"{d}/x"):
                        for f in fs:
                            if _utile(f) and len(interni) < 40:
                                p = os.path.join(root, f)
                                if os.path.getsize(p) < (MAX_ARCH if f.lower().endswith((".zip", ".7z", ".rar")) else MAX_FILE):
                                    interni.append((os.path.relpath(p, f"{d}/x"), open(p, "rb").read()))
        except Exception:
            out.append((nome, data))
            continue
        base = os.path.basename(nome)
        out += espandi([(f"{base}/{x}", b) for x, b in interni], livello + 1)
    return out


def salva_gara(files, cart):
    """Estrae i testi e salva testi.json.gz nella cartella della gara. Restituisce l'elenco dei documenti."""
    os.makedirs(cart, exist_ok=True)
    docs = []
    files = espandi(files)
    for nome, data in files:
        try:
            formato, testo = testo_da(nome, data)
        except Exception:
            formato, testo = "errore", ""
        docs.append({"nome": nome[:150], "tipo": tipo_doc(nome), "formato": formato,
                     "kb": len(data) // 1024, "caratteri": len(testo), "testo": testo})
    docs.sort(key=lambda x: PRIORITA.index(x["tipo"]))
    # computo metrico ed elenco prezzi: testo intero a parte (servono all'analisi del margine)
    comp = [{"nome": x["nome"], "tipo": x["tipo"], "testo": x["testo"][:3_000_000]} for x in docs
            if x["tipo"] in ("computo", "elenco_prezzi") or re.search(r"manodopera|quadro.?econ", x["nome"], re.I)]
    if comp:
        with gzip.open(f"{cart}/computo.json.gz", "wt", encoding="utf-8") as f:
            json.dump(comp, f, ensure_ascii=False)
    # stesso testo due volte (file firmato .p7m e copia in chiaro): lo tengo una volta sola
    visti = set()
    for x in docs:
        h = hash(x["testo"][:5000]) if len(x["testo"]) > 200 else None
        if h in visti:
            x["testo"], x["doppio"] = "", True
        elif h:
            visti.add(h)
    # budget per tipo: i documenti di gara interi, poi relazione e capitolato, il resto si divide quel che avanza
    TETTO = {"disciplinare": 250_000, "lettera_invito": 250_000, "bando": 250_000, "avviso": 150_000,
             "relazione": 100_000, "capitolato": 60_000}
    budget = MAX_TESTO
    quota = [0] * len(docs)
    for i, x in enumerate(docs):
        if x["tipo"] in TETTO:
            quota[i] = min(len(x["testo"]), TETTO[x["tipo"]], budget)
            budget -= quota[i]
    resto = [i for i, x in enumerate(docs) if x["tipo"] not in TETTO and x["testo"]]
    for n, i in enumerate(resto):
        quota[i] = min(len(docs[i]["testo"]), 40_000, budget // max(1, len(resto) - n))
        budget -= quota[i]
    out = []
    for i, x in enumerate(docs):
        out.append({**x, "testo": x.pop("testo")[:quota[i]]})
    with gzip.open(f"{cart}/testi.json.gz", "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return docs


CONDIVISI = re.compile(r"https?://[^\s\"'<>]*?(?:/index\.php)?/s/[A-Za-z0-9]{8,}|https?://(?:www\.)?dropbox\.com/[^\s\"'<>]+|"
                       r"https?://drive\.google\.com/[^\s\"'<>]+|https?://(?:[\w-]+\.)?sharepoint\.com/[^\s\"'<>]+", re.I)


def link_esterni(files):
    """Il progetto è spesso su un cloud dell'ente (Nextcloud/ownCloud, Google Drive, Dropbox) indicato in un PDF:
    trova quei link nei documenti piccoli e restituisce gli URL di download diretto."""
    out = []
    for nome, data in files:
        if len(data) > 3_000_000 or not (data[:4] == b"%PDF" or nome.lower().endswith((".pdf", ".p7m", ".txt", ".html"))):
            continue
        try:
            _, t = testo_da(nome, data)
        except Exception:
            continue
        for u in CONDIVISI.findall(t.replace("\n", " ")):
            u = u.rstrip(".,;)")
            if "/s/" in u and "drive.google" not in u:            # Nextcloud / ownCloud: cartella o file condiviso
                out.append(u.split("?")[0].rstrip("/") + "/download")
            elif "dropbox.com" in u:
                out.append(re.sub(r"([?&])dl=0", r"\1dl=1", u) if "dl=" in u else u + ("&" if "?" in u else "?") + "dl=1")
            elif "drive.google.com" in u:
                m = re.search(r"/d/([\w-]{20,})|id=([\w-]{20,})", u)
                if m and "/folders/" not in u:
                    out.append(f"https://drive.google.com/uc?export=download&id={m.group(1) or m.group(2)}")
    return list(dict.fromkeys(out))[:3]


def scarica_esterno(u):
    """Scarica un progetto da un link di condivisione pubblico (fino a 250 MB)."""
    req = urllib.request.Request(u, headers={"user-agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        buf, fine = bytearray(), time.time() + 170
        while True:
            pz = r.read(1 << 20)
            if not pz:
                break
            buf += pz
            if len(buf) > 250 * 1024 * 1024 or time.time() > fine:
                raise ValueError("troppo grande o lento")
        cd = r.headers.get("content-disposition") or ""
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        nome = unquote(m.group(1)) if m else "progetto_esterno" + (".zip" if buf[:2] == b"PK" else "")
        return nome, bytes(buf)


def senza_doppi(files):
    visti, out = set(), []
    for nome, data in files:
        k = (os.path.basename(nome).lower(), len(data))
        if k not in visti:
            visti.add(k)
            out.append((nome, data))
    return out


def una(url, cart, cig="", titolo=""):
    """Processo figlio: una sola pagina di gara, con tempo limitato dal processo padre."""
    global _proxy_url
    try:
        esito, metodo, files = gara(cig, url, titolo)
    except Exception as e:
        esito, metodo, files = f"errore {type(e).__name__}", "diretto", []
    files = senza_doppi(files)
    # progetto su cloud esterno (link dentro un PDF di gara)
    esterni, presi = link_esterni(files), 0
    for u in esterni:
        try:
            files.append(scarica_esterno(u))
            metodo += "+cloud"
            presi += 1
        except Exception:
            pass
    nf = 0
    if files:
        docs = salva_gara(files, cart)
        nf = len(files)
        if not any(x["caratteri"] > 500 for x in docs):
            esito = "file senza testo (scansioni?)"
        elif esterni and not presi:
            esito = "progetto su cloud da scaricare dall'Italia"   # lo riprova il server italiano
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
                               capture_output=True, text=True, timeout=420)
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



def giorno_default():
    """Di sera (dalle 18 ora italiana) il giorno stesso, per il giro serale; altrimenti ieri."""
    from zoneinfo import ZoneInfo
    ora = datetime.now(ZoneInfo("Europe/Rome"))
    return (ora if ora.hour >= 18 else ora - timedelta(days=1)).strftime("%d/%m/%Y")


def main():
    giorno = os.environ.get("DATA") or giorno_default()
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
    solo = {x.strip() for x in (os.environ.get("SOLO_CIG") or "").split(",") if x.strip()}
    if solo:
        righe = [r for r in righe if r[0] in solo]
    base = f"testi/{d:%Y/%m/%d}"
    gia_ok = set()
    if not solo and os.path.exists(f"{base}/rapporto.json"):   # giro del mattino dopo quello serale: solo le gare nuove o fallite
        gia_ok = {r["cig"] for r in json.load(open(f"{base}/rapporto.json")) if r.get("esito") == "ok"}
        righe = [r for r in righe if r[0] not in gia_ok]
        print(f"   {len(gia_ok)} gare già lette nel giro precedente", flush=True)
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
    DA_RIFARE = ("bloccata", "link senza file", "nessun file trovato", "troppo lenta", "errore", "file senza testo",
                 "progetto su cloud da scaricare dall'Italia")
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
    if (solo or gia_ok) and os.path.exists(f"{base}/rapporto.json"):   # tengo le gare già lette, aggiorno le altre
        nuovi = {r["cig"] for r in rapporto}
        vecchio = [r for r in json.load(open(f"{base}/rapporto.json")) if r["cig"] not in nuovi and (r["cig"] not in solo if solo else r["cig"] in gia_ok)]
        rapporto = vecchio + rapporto
    os.makedirs(base, exist_ok=True)
    json.dump(rapporto, open(f"{base}/rapporto.json", "w"), ensure_ascii=False, indent=1)
    if not solo:
        from zoneinfo import ZoneInfo
        giro = "mattina" if datetime.now(ZoneInfo("Europe/Rome")).hour < 18 else "sera"
        open(f"{base}/giro_{giro}", "w").write(datetime.now(timezone.utc).isoformat())
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
