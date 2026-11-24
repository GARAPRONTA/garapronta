"""Chrome vero con proxy italiano (residenziale) per START Toscana, MEPA e piattaforme che rifiutano i programmi."""
import asyncio, base64, hashlib, re
from urllib.parse import urlparse, unquote
from apify import Actor
from playwright.async_api import async_playwright
import lettori

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def nome_da(cd, url):
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd or "") or re.search(r'filename="?([^";]+)', cd or "")
    return unquote(m.group(1)).strip() if m else (unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "documento")


async def una(browser, proxy, page_url):
    pu = urlparse(proxy)
    ctx = await browser.new_context(user_agent=UA, locale="it-IT", accept_downloads=True, ignore_https_errors=True,
                                    proxy={"server": f"http://{pu.hostname}:{pu.port}", "username": unquote(pu.username), "password": unquote(pu.password)})
    await ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "font", "media", "stylesheet") else r.continue_())
    pg = await ctx.new_page()
    files = []
    try:
        await pg.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(5000)
        m = re.search(r"/tenders/([0-9]{6}-[0-9]{4})", page_url)
        if "start.toscana.it" in page_url and m:
            for n, d in await pg.evaluate(lettori.JS_START, m.group(1)):
                files.append((n, base64.b64decode(d)))
            return files
        for t in ("Documenti di gara", "Documentazione", "Documenti", "Allegati"):
            try:
                await pg.get_by_text(t, exact=True).first.click(timeout=2500)
                await pg.wait_for_timeout(3000)
                break
            except Exception:
                pass
        html = await pg.content()
        for fr in pg.frames[1:]:
            try:
                html += await fr.content()
            except Exception:
                pass
        links = lettori.link_file(html, pg.url)
        for u in links[:8]:
            try:
                r = await ctx.request.get(u, timeout=60000, headers={"referer": pg.url})
                body = await r.body()
                ct = r.headers.get("content-type", "")
                if r.ok and body and not ("text/html" in ct and body[:4] != b"%PDF") and len(body) < 15_000_000:
                    files.append((nome_da(r.headers.get("content-disposition"), u), body))
            except Exception:
                continue
        if not files:   # es. MEPA: i documenti si scaricano cliccando
            cand = pg.locator("text=/\\.(pdf|p7m|zip)\\s*$/i")
            for i in range(min(await cand.count(), 8)):
                try:
                    async with pg.expect_download(timeout=20000) as dl:
                        await cand.nth(i).click(timeout=5000)
                    d = await dl.value
                    files.append((d.suggested_filename, open(await d.path(), "rb").read()))
                except Exception:
                    continue
    finally:
        await ctx.close()
    return files


async def main():
    async with Actor:
        inp = await Actor.get_input() or {}
        pages = inp.get("pages") or []
        pc = await Actor.create_proxy_configuration(groups=["RESIDENTIAL"], country_code="IT")
        kv = await Actor.open_key_value_store()
        sem = asyncio.Semaphore(3)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            async def job(u):
                async with sem:
                    proxy = await pc.new_url(session_id=hashlib.md5(u.encode()).hexdigest()[:10])
                    try:
                        files = await asyncio.wait_for(una(browser, proxy, u), timeout=240)
                        esito = "ok" if files else "nessun file"
                    except Exception as e:
                        files, esito = [], f"errore {type(e).__name__}"
                    rec = {"page": u, "esito": esito, "files": []}
                    for n, data in files:
                        key = hashlib.sha1((u + n).encode()).hexdigest()[:20]
                        await kv.set_value(key, data, content_type="application/octet-stream")
                        rec["files"].append({"nome": n, "key": key, "kb": len(data) // 1024})
                    await Actor.push_data(rec)
            await asyncio.gather(*(job(u) for u in pages))
            await browser.close()

asyncio.run(main())
