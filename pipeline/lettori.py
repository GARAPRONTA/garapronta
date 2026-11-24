"""GaraPronta — lettori delle piattaforme di gara (condivisi tra GitHub e l'actor Apify).

Uso: trova(url, cig, titolo, get) -> lista di elementi:
      ("url", link_al_file)            da scaricare con la stessa sessione
      ("file", nome, bytes)            già scaricato (es. START)
`get(url, method="GET", data=None, headers=None)` -> (status, headers_minuscoli, bytes, url_finale)
"""
import base64, json, re
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qs, unquote

JS_START = """async (tid) => {
  const j = async u => { const r = await fetch(u); return r.ok ? r.json() : null };
  let tipo = 'open_procedure';
  try { const t = await (await fetch('/tendering-api/tenders/tenderType/' + tid)).text(); if (t && t.length < 60) tipo = t.replace(/"/g,''); } catch(e) {}
  const info = await j(`/tendering-api/tenders/${tipo}/${tid}/basic-info`);
  if (!info) return [];
  const pr = s => { s = s.toLowerCase(); const k = ['disciplinar','invito','bando','avviso','criteri','capitolat']; for (let i=0;i<k.length;i++) if (s.includes(k[i])) return i; return 10; };
  const atts = (info.attachments||[]).filter(a => a.file && a.whoCanDownload === 'anyone' && !a.isDeleted)
     .sort((a,b) => pr(((a.description||{}).it_IT||'')+a.file.fileName) - pr(((b.description||{}).it_IT||'')+b.file.fileName)).slice(0,10);
  const out = [];
  for (const a of atts) {
    try {
      const t = await j(`/tendering-api/tenders/${tipo}/${tid}/attachments/${a.id}/template`);
      const r = await fetch(t.redirectUrl); const b = new Uint8Array(await r.arrayBuffer());
      let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768));
      out.push([a.file.fileName, btoa(s)]);
    } catch(e) {}
  }
  return out;
}"""

EST = (".pdf", ".p7m", ".zip", ".doc", ".docx", ".rtf", ".odt")
PATTERN = [
    r"/?allegati/open\.php\?[^\"'\s<>]+",                                   # TuttoGare
    r"[^\"'\s<>]*downloadDocumentoPubblico\.action[^\"'\s<>]*",            # Maggioli PortaleAppalti
    r"[^\"'\s<>]*fs_public_action\?do=download_document[^\"'\s<>]*",       # Traspare
    r"[^\"'\s<>]*/file/download/[^\"'\s<>]+",                              # DigitalPA / acquistitelematici
]


def js_escape(s):
    """Equivalente di escape() di JavaScript (usato da SardegnaCAT/EmPULIA/Intercent-ER e simili)."""
    out = []
    for ch in s:
        if ch.isascii() and (ch.isalnum() or ch in "@*_+-./"):
            out.append(ch)
        elif ord(ch) < 256:
            out.append("%%%02X" % ord(ch))
        else:
            out.append("%%u%04X" % ord(ch))
    return "".join(out)


def _prio(h):
    n = h.lower()
    try:
        q = parse_qs(urlparse(h).query)
        if "filename" in q:
            n += base64.b64decode(q["filename"][0]).decode("utf-8", "ignore").lower()
        if "TECHVALUE" in h:
            n += unquote(h).lower()
    except Exception:
        pass
    for i, k in enumerate(["disciplinar", "invito", "bando", "avviso", "criteri", "capitolat", "elenco", "computo"]):
        if k in n:
            return i
    return 20 if re.search(r"progett|elaborat|tavol|esecutiv|\.zip", n) else 10


def link_file(html, base):
    html = unescape(html)
    trovati = []
    for p in PATTERN:
        trovati += re.findall(p, html)
    # Piattaforme "AF" (SardegnaCAT, EmPULIA, Intercent-ER, aflink): window.open('…TECHVALUE=' + escape('…') + '…')
    for a, b, c in re.findall(r"""['"](https?://[^'"]*?DisplayAttach\.ASP\?[^'"]*?TECHVALUE=)['"]\s*\+\s*escape\(\s*['"]([^'"]+)['"]\s*\)\s*\+\s*['"]([^'"]*)['"]""", html, re.I):
        trovati.append(a + js_escape(b) + c)
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.I):
        h = href.lower()
        if (h.split("?")[0].endswith(EST) or re.search(r"(download|scarica|getfile|allegato|attachment)[^/]*([?=&]|$)", h)) \
                and not re.search(r"(login|registra|password|javascript:|mailto:|verifica|cookie|privacy)", h):
            trovati.append(href)
    trovati.sort(key=_prio)
    out, visti = [], set()
    for t in trovati:
        u = re.sub(r";jsessionid=[^?]+", "", urljoin(base, t.strip()))
        if u not in visti and urlparse(u).scheme in ("http", "https"):
            visti.add(u)
            out.append(u)
    return out[:30]


# ---------------------------------------------------------------- START Toscana (API pubblica)
def start_toscana(url, get):
    m = re.search(r"/tenders/([0-9]{6}-[0-9]{4})", url)
    if not m:
        return []
    tid = m.group(1)
    host = "https://" + urlparse(url).netloc
    st, h, body, _ = get(f"{host}/tendering-api/tenders/tenderType/{tid}", headers={"accept": "application/json"})
    tipo = body.decode("utf-8", "ignore").strip().strip('"') if st == 200 else "open_procedure"
    try:
        tipo = json.loads(body).get("type", tipo) if body[:1] == b"{" else tipo
    except Exception:
        pass
    st, h, body, _ = get(f"{host}/tendering-api/tenders/{tipo}/{tid}/basic-info", headers={"accept": "application/json"})
    if st != 200:
        return []
    info = json.loads(body)
    atts = [a for a in info.get("attachments") or [] if a.get("file") and a.get("whoCanDownload") == "anyone"
            and not a.get("isDeleted")]
    atts.sort(key=lambda a: _prio(((a.get("description") or {}).get("it_IT") or "") + (a["file"].get("fileName") or "")))
    out = []
    for a in atts[:12]:
        st, h, body, _ = get(f"{host}/tendering-api/tenders/{tipo}/{tid}/attachments/{a['id']}/template",
                             headers={"accept": "application/json"})
        if st != 200:
            continue
        red = json.loads(body).get("redirectUrl")
        if not red:
            continue
        st, h, data, _ = get(urljoin(host, red))
        if st == 200 and data:
            out.append(("file", a["file"].get("fileName") or "documento", data))
    return out


# ---------------------------------------------------------------- link generici (home page dell'ente)
def cerca_cig(html, base, cig, titolo, get, profondita=2, max_pagine=12):
    """Il link ANAC porta spesso alla home o all'elenco bandi: cerca la pagina della gara tramite CIG o titolo."""
    parole = [w for w in re.findall(r"[a-zà-ù]{5,}", (titolo or "").lower())][:8]
    visti, coda = {base}, [(html, base, 0)]
    pagine = 0
    while coda and pagine < max_pagine:
        h, b, d = coda.pop(0)
        hs = unescape(h)
        anchors = re.findall(r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", hs, re.I | re.S)
        # 1) link vicino al CIG o con molte parole del titolo
        migliori = []
        for href, testo in anchors:
            t = re.sub(r"<[^>]+>", " ", testo).lower()
            score = (10 if cig and (cig.lower() in t or cig.lower() in href.lower()) else 0) + sum(w in t for w in parole)
            if score >= 3:
                migliori.append((score, href))
        if cig and cig in hs and not migliori:
            i = hs.find(cig)
            vicino = re.findall(r"href=[\"']([^\"'#]+)[\"']", hs[max(0, i - 3000): i + 3000])
            migliori += [(5, x) for x in vicino if re.search(r"dettagli|bando|gara|procedur|avvis|announcement|tender", x, re.I)]
        for _, href in sorted(migliori, reverse=True)[:3]:
            u = urljoin(b, href)
            if u in visti:
                continue
            visti.add(u)
            st, hh, body, fu = get(u)
            pagine += 1
            if body[:4] == b"%PDF":
                return [("file", unquote(urlparse(u).path.rsplit("/", 1)[-1]) or "documento.pdf", body)]
            l = link_file(body.decode("utf-8", "ignore"), fu)
            if l:
                return [("url", x) for x in l]
        # 2) altrimenti segui le sezioni bandi/gare/appalti
        if d < profondita:
            for href, testo in anchors:
                t = re.sub(r"<[^>]+>", " ", testo).lower() + " " + href.lower()
                if re.search(r"bandi|gare|appalt|avvisi|procedure in corso|bandi di gara", t):
                    u = urljoin(b, href)
                    if u in visti or urlparse(u).netloc != urlparse(base).netloc:
                        continue
                    visti.add(u)
                    try:
                        st, hh, body, fu = get(u)
                        pagine += 1
                        if st == 200 and b"<" in body[:2000]:
                            coda.append((body.decode("utf-8", "ignore"), fu, d + 1))
                    except Exception:
                        continue
                    if pagine >= max_pagine:
                        break
    return []


def intercenter(url, get):
    """Intercent-ER: la scheda del bando ha un'API JSON pubblica (++api++) con l'elenco degli allegati."""
    m = re.search(r"BANDO_GARA_PORTALE@(\d+)", url)
    if not m:
        return []
    st, h, body, fu = get(f"https://intercenter.regione.emilia-romagna.it/trovabando/BANDO_GARA_PORTALE@{m.group(1)}")
    if st >= 400 or "/++api++/" in fu:
        return []
    api = fu.replace("emilia-romagna.it/", "emilia-romagna.it/++api++/", 1)
    st, h, body, _ = get(api, headers={"accept": "application/json"})
    if st != 200:
        return []
    d = ((json.loads(body).get("@components") or {}).get("intercenter-data") or {}).get("data") or {}
    alle = [a for a in d.get("allegati") or [] if a.get("url")]
    alle.sort(key=lambda a: _prio((a.get("descrizione") or "") + " " + (a.get("nome") or "")))
    return [("url", a["url"].replace(" ", "%20")) for a in alle[:15]]


def trova(url, cig, titolo, get):
    """Restituisce i documenti da scaricare per una gara."""
    if "intercenter.regione.emilia-romagna.it" in url and "BANDO_GARA_PORTALE@" in url:
        return intercenter(url, get)
    if "start.toscana.it" in url and "/tenders/" in url:
        return start_toscana(url, get)
    st, h, body, fu = get(url)
    if st >= 400:
        raise PermissionError(f"HTTP {st}")
    if body[:4] == b"%PDF":
        return [("file", unquote(urlparse(fu).path.rsplit("/", 1)[-1]) or "documento.pdf", body)]
    html = body.decode("utf-8", "ignore")
    links = link_file(html, fu)
    if links:
        return [("url", x) for x in links]
    return cerca_cig(html, fu, cig, titolo, get)
