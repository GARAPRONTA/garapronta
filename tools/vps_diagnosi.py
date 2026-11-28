"""Diagnosi sul server italiano: API di START Toscana sulle gare fallite e PDF scansionati."""
import json, sys, re, subprocess, time
sys.path.insert(0, "/opt/garapronta")
import documenti, lettori
URLS = ['https://start.toscana.it/tendering/tenders/048007-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/047824-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/048481-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/047667-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/049143-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/049164-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/049221-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/048578-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/032775-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/049730-2026/view/detail/1', 'https://start.toscana.it/tendering/tenders/049760-2026/view/detail/1']
for url in URLS:
    tid = re.search(r"/tenders/([0-9]{6}-[0-9]{4})", url).group(1)
    st, h, b, _ = documenti._get(f"https://start.toscana.it/tendering-api/tenders/tenderType/{tid}", headers={"accept": "application/json"})
    print("==", tid, "tipo", st, b[:120])
    tipo = b.decode().strip().strip('"') if st == 200 else "?"
    try:
        tipo = json.loads(b).get("type", tipo) if b[:1] == b"{" else tipo
    except Exception:
        pass
    st, h, b, _ = documenti._get(f"https://start.toscana.it/tendering-api/tenders/{tipo}/{tid}/basic-info", headers={"accept": "application/json"})
    print("   basic-info", st, len(b))
    if st == 200:
        info = json.loads(b)
        at = info.get("attachments") or []
        print("   allegati", len(at), [(a.get("whoCanDownload"), (a.get("file") or {}).get("fileName")) for a in at][:12])
        print("   chiavi", list(info.keys())[:40])
t = time.time()
p = subprocess.run([sys.executable, "/opt/garapronta/documenti.py", "--una", "https://provincia-isernia.acquistitelematici.it/tender/664", "/tmp/dg/is", "BDE97FCD8C", ""], capture_output=True, text=True, timeout=400)
print("isernia", round(time.time() - t), p.stdout[-300:], p.stderr[-800:])
import gzip
for d in json.load(gzip.open("/tmp/dg/is/testi.json.gz", "rt")):
    print("   ", d["nome"][:60], d["tipo"], d["kb"], d["caratteri"])
