"""Gira dentro Apify con il proxy italiano: apre le pagine di gara, trova i link ai documenti
e li scarica nella stessa sessione. Salva i file nel key-value store e un riepilogo nel dataset."""
import asyncio, base64, hashlib, re
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import httpx
from apify import Actor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
EST = (".pdf", ".p7m", ".zip", ".doc", ".docx", ".rtf", ".odt")
PAT = [r"/?allegati/open\.php\?[^\"'\s<>]+", r"[^\"'\s<>]*downloadDocumentoPubblico\.action[^\"'\s<>]*",
       r"[^\"'\s<>]*fs_public_action\?do=download_document[^\"'\s<>]*"]


def links(html, base):
    html = unescape(html)
    out = []
    for p in PAT:
        out += re.findall(p, html)
    for h in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.I):
        hl = h.lower()
        if (hl.split("?")[0].endswith(EST) or re.search(r"(download|scarica|getfile|allegato|attachment)[^/]*([?=&]|$)", hl)) \
                and not re.search(r"(login|registra|password|javascript:|mailto:|verifica)", hl):
            out.append(h)
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
    out.sort(key=prio)
    res, seen = [], set()
    for t in out:
        u = re.sub(r";jsessionid=[^?]+", "", urljoin(base, t.strip()))
        if u not in seen and urlparse(u).scheme in ("http", "https"):
            seen.add(u); res.append(u)
    return res[:30]


def nome(url, h):
    cd = h.get("content-disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)', cd)
    if m:
        return unquote(m.group(1)).strip()
    q = parse_qs(urlparse(url).query)
    if "filename" in q:
        try:
            return base64.b64decode(q["filename"][0]).decode("utf-8", "ignore")
        except Exception:
            pass
    return unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "documento"


async def una(page, proxy, kv):
    rec = {"page": page, "esito": "", "files": []}
    try:
        async with httpx.AsyncClient(proxy=proxy, headers={"user-agent": UA, "accept-language": "it-IT,it;q=0.9"},
                                     follow_redirects=True, timeout=httpx.Timeout(30, connect=15), verify=False) as c:
            r = await c.get(page)
            ct = r.headers.get("content-type", "")
            if r.content[:4] == b"%PDF":
                cand = [(page, r)]
            else:
                if r.status_code >= 400:
                    rec["esito"] = f"HTTP {r.status_code}"; return rec
                cand = []
                for u in links(r.text, str(r.url)):
                    if len(cand) >= 8:
                        break
                    try:
                        f = await c.get(u, headers={"referer": str(r.url)})
                        if "text/html" in f.headers.get("content-type", "") and f.content[:4] != b"%PDF":
                            continue
                        if len(f.content) > 15_000_000:
                            continue
                        cand.append((u, f))
                    except Exception:
                        continue
            for u, f in cand:
                key = hashlib.sha1(u.encode()).hexdigest()[:20]
                await kv.set_value(key, f.content, content_type="application/octet-stream")
                rec["files"].append({"url": u, "nome": nome(u, f.headers), "key": key, "kb": len(f.content) // 1024})
            rec["esito"] = "ok" if rec["files"] else "nessun file"
    except Exception as e:
        rec["esito"] = f"errore {type(e).__name__}"
    return rec


async def main():
    async with Actor:
        inp = await Actor.get_input() or {}
        pages = inp.get("pages") or []
        pc = await Actor.create_proxy_configuration(groups=["RESIDENTIAL"], country_code="IT")
        kv = await Actor.open_key_value_store()
        sem = asyncio.Semaphore(6)

        async def job(p):
            async with sem:
                proxy = await pc.new_url(session_id=hashlib.md5(p.encode()).hexdigest()[:10])
                rec = await una(p, proxy, kv)
                await Actor.push_data(rec)
        await asyncio.gather(*(job(p) for p in pages))

asyncio.run(main())
