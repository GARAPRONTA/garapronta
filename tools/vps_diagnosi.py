"""Diagnosi sul server italiano: prova il lettore su alcune gare difficili e stampa tutto (anche gli errori)."""
import json, os, subprocess, sys, time
sys.path.insert(0, "/opt/garapronta")
PROVE = [
    ("BE000B7CB4", "https://start.toscana.it/tendering/tenders/049730-2026/view/detail/1"),
    ("BDFBBFB409", "https://sua-mbcmm.acquistitelematici.it/tender/741"),
    ("BE01543168", "https://peccioli.trasparenza-valutazione-merito.it/web/trasparenza/papca-g/-/papca/display/10621828"),
    ("BDE8E04395", "https://www.sintel.regione.lombardia.it/eprocdata/auctionDetail.xhtml?id=226856892"),
    ("BDFFE68501", "https://provinciacomo-appalti.maggiolicloud.it/PortaleAppalti/it/procedure/codice/G01790"),
]
print("tesseract:", subprocess.run(["which", "tesseract"], capture_output=True, text=True).stdout.strip() or "NO")
for cig, url in PROVE:
    t = time.time()
    p = subprocess.run([sys.executable, "/opt/garapronta/documenti.py", "--una", url, f"/tmp/dg/{cig}", cig, ""],
                       capture_output=True, text=True, timeout=400)
    print(f"== {cig} {round(time.time() - t)}s {url}")
    print("   OUT:", p.stdout.strip()[-600:])
    print("   ERR:", p.stderr.strip()[-1500:])
    try:
        for d in json.load(open(f"/tmp/dg/{cig}/indice.json"))[:15]:
            print("     ", d.get("nome", "")[:70], d.get("tipo"), d.get("caratteri"))
    except Exception as e:
        print("   (nessun indice)", e)
