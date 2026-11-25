"""Sul server italiano: scarica i prezzari regionali 2026 trovati e mostra com'è fatto ogni file."""
import io, json, os, re, urllib.request, zipfile
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
D = "/opt/garapronta/prezzari"; os.makedirs(D, exist_ok=True)
L = json.load(open("/opt/garapronta/prezzari_link.json"))
PREF = [r"\.csv", r"\.xlsx", r"\.xls\b|\.xls/", r"\.ods", r"\.zip", r"\.xml"]


def scegli(reg, links):
    c = [(h, t) for h, t in links if "2026" in (h + t)] or ([(h, t) for h, t in links if "editabil" in (h + t).lower()])
    for p in PREF:
        for h, t in c:
            if re.search(p, h, re.I) and "brevi" not in h.lower() and "confronto" not in h.lower() and "conversione" not in t.lower():
                return h
    return None


def mostra(nome, data):
    print(f"   file {nome} · {len(data) // 1024} KB")
    if nome.lower().endswith(".zip") or data[:2] == b"PK" and not re.search(r"\.(xlsx|ods)$", nome, re.I):
        z = zipfile.ZipFile(io.BytesIO(data)); print("   zip:", z.namelist()[:15]); return
    if re.search(r"\.xlsx$|xlsx", nome, re.I) or data[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        for ws in wb.worksheets[:3]:
            print("   foglio", ws.title, ws.max_row, "righe")
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                if i > 6: break
                print("     ", [str(x)[:40] for x in r[:10]])
        return
    txt = data[:3000].decode("utf-8", "ignore") if data[:5] != b"\xd0\xcf\x11\xe0\xa1" else "(xls binario)"
    print("   ", txt[:1500].replace("\n", " ⏎ "))


for reg, links in L.items():
    u = scegli(reg, links)
    if not u:
        continue
    print(f"\n## {reg}: {u[:160]}", flush=True)
    try:
        data = urllib.request.urlopen(urllib.request.Request(u, headers={"user-agent": UA}), timeout=300).read()
        nome = re.sub(r"[^\w.\-]", "_", reg) + "_" + os.path.basename(u.split("/@@")[0].split("?")[0])[-60:]
        open(f"{D}/{nome}", "wb").write(data)
        mostra(nome, data)
    except Exception as e:
        print("   ERRORE", e)
