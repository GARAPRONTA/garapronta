"""Gira dentro Apify con il proxy italiano. Usa gli stessi lettori di GitHub (lettori.py, copiato al deploy)."""
import asyncio, hashlib, re
from urllib.parse import urlparse, parse_qs, unquote
import base64
import httpx
from apify import Actor
import lettori

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


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


def una(page, cig, titolo, proxy):
    """Sincrona (in un thread): una sessione per gara, così cookie e referer restano coerenti."""
    out, ref = [], [None]
    with httpx.Client(proxy=proxy, follow_redirects=True, verify=False,
                      timeout=httpx.Timeout(30, connect=15),
                      headers={"user-agent": UA, "accept-language": "it-IT,it;q=0.9"}) as c:
        def get(url, method="GET", data=None, headers=None):
            h = dict(headers or {})
            if ref[0]:
                h.setdefault("referer", ref[0])
            r = c.request(method, url, content=data, headers=h)
            if len(r.content) > 15_000_000:
                return 413, {}, b"", str(r.url)
            hd = {k.lower(): v for k, v in r.headers.items()}
            if "text/html" in hd.get("content-type", ""):
                ref[0] = str(r.url)
            return r.status_code, hd, r.content, str(r.url)
        try:
            elementi = lettori.trova(page, cig, titolo, get)
        except Exception as e:
            return f"errore {type(e).__name__}", []
        for el in elementi:
            if len(out) >= 8:
                break
            if el[0] == "file":
                out.append((el[1], el[2])); continue
            try:
                st, hd, data, _ = get(el[1])
                if st == 200 and data and not ("text/html" in hd.get("content-type", "") and data[:4] != b"%PDF"):
                    out.append((nome(el[1], hd), data))
            except Exception:
                continue
    return ("ok" if out else "nessun file"), out


async def main():
    async with Actor:
        inp = await Actor.get_input() or {}
        pages, info = inp.get("pages") or [], inp.get("info") or {}
        pc = await Actor.create_proxy_configuration(groups=["RESIDENTIAL"], country_code="IT")
        kv = await Actor.open_key_value_store()
        sem = asyncio.Semaphore(10)

        async def job(p):
            async with sem:
                proxy = await pc.new_url(session_id=hashlib.md5(p.encode()).hexdigest()[:10])
                cig, titolo = (info.get(p) or ["", ""])[:2]
                try:
                    esito, files = await asyncio.wait_for(asyncio.to_thread(una, p, cig, titolo, proxy), timeout=180)
                except asyncio.TimeoutError:
                    esito, files = "troppo lenta", []
                rec = {"page": p, "esito": esito, "files": []}
                for n, data in files:
                    key = hashlib.sha1((p + n).encode()).hexdigest()[:20]
                    await kv.set_value(key, data, content_type="application/octet-stream")
                    rec["files"].append({"nome": n, "key": key, "kb": len(data) // 1024})
                await Actor.push_data(rec)
        await asyncio.gather(*(job(p) for p in pages))

asyncio.run(main())
