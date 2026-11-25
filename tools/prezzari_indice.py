"""Sul server italiano: legge i prezzari regionali scaricati (xlsx, xls, csv, ods, zip) con un lettore unico
e scrive un indice per regione:  /opt/garapronta/indici/prezzari/<Regione>.json.gz  {codice: [prezzo, um, descrizione]}"""
import csv, glob, gzip, io, json, os, re, subprocess, zipfile

D = "/opt/garapronta/prezzari"
OUT = "/opt/garapronta/indici/prezzari"
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

# file in piu' rispetto alla ricerca automatica (scaricati con curl: alcuni siti hanno certificati incompleti)
EXTRA = {
    "Abruzzo": "https://www.regione.abruzzo.it/sites/default/files/allegati/3524/2026-08-05/prezzario-abruzzo-2026-editabile.zip",
}
for reg, u in EXTRA.items():
    dest = f"{D}/{reg}_{os.path.basename(u)}"
    if not os.path.exists(dest):
        subprocess.run(["curl", "-fsSL", "-k", "-A", UA, "-o", dest, u], timeout=600)

COD = re.compile(r"^[A-Z0-9]{1,6}([._\-/ ][A-Z0-9]{1,8}){1,7}$", re.I)
UM = re.compile(r"^(m|m2|m²|mq|m3|m³|mc|ml|kg|t|q|cad|cad\.|n|nr|n\.|a corpo|ora|h|ore|giorno|gg|l|lt|km|dm3|cm|mese|%|kw|cadauno|corpo|mt|tonn)\b", re.I)


def numero(x):
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x or "").strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def da_riga(cells):
    """Riconosce in una riga: codice (prima cella che sembra un codice), prezzo (ultimo numero plausibile dopo l'unità), unità, descrizione."""
    vals = [("" if c is None else str(c)).strip() for c in cells]
    cod = next((v for v in vals[:4] if v and COD.match(v) and any(ch.isdigit() for ch in v)), None)
    if not cod:
        return None
    i_um = next((i for i, v in enumerate(vals) if v and len(v) <= 12 and UM.match(v)), None)
    if i_um is None:
        return None
    prezzo = next((numero(v) for v in vals[i_um + 1:] if numero(v) is not None and numero(v) > 0), None)
    if prezzo is None or prezzo > 5_000_000:
        return None
    descr = max((v for v in vals if v and v != cod and not UM.match(v) and numero(v) is None), key=len, default="")
    return cod.upper().replace(" ", ""), prezzo, vals[i_um], descr[:90]


def righe_file(nome, data):
    n = nome.lower()
    if n.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        for f in z.namelist():
            if re.search(r"\.(xlsx|xls|csv|ods)$", f, re.I) and not re.search(r"analisi|confronto|conversione", f, re.I):
                yield from righe_file(f, z.read(f))
        return
    if n.endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            yield from ws.iter_rows(values_only=True)
        return
    if n.endswith(".xls") or data[:5] == b"\xd0\xcf\x11\xe0\xa1":
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        for sh in wb.sheets():
            for r in range(sh.nrows):
                yield sh.row_values(r)
        return
    if n.endswith(".ods"):
        import pandas as pd
        for _, df in pd.read_excel(io.BytesIO(data), engine="odf", sheet_name=None, header=None).items():
            yield from df.itertuples(index=False)
        return
    if n.endswith(".csv"):
        txt = data.decode("utf-8", "ignore") if data[:3] == b"\xef\xbb\xbf" or b"\xc3" in data[:20000] else data.decode("latin-1")
        sep = ";" if txt.count(";") > txt.count(",") else ","
        yield from csv.reader(io.StringIO(txt), delimiter=sep)


per_reg = {}
for f in sorted(glob.glob(f"{D}/*")):
    reg = os.path.basename(f).split("_")[0].replace("-", " ").replace("Friuli Venezia Giulia", "Friuli-Venezia Giulia").replace("Emilia Romagna", "Emilia-Romagna")
    if re.search(r"analisi|confronto|brevi|2024|2025", f, re.I):
        continue
    try:
        data = open(f, "rb").read()
        n = 0
        for r in righe_file(f, data):
            x = da_riga(list(r))
            if x:
                per_reg.setdefault(reg, {})[x[0]] = [x[1], x[2], x[3]]
                n += 1
        print(f"{reg:24} {os.path.basename(f)[:60]:60} voci {n}", flush=True)
    except Exception as e:
        print(f"{reg:24} {os.path.basename(f)[:60]:60} ERRORE {type(e).__name__}: {str(e)[:120]}", flush=True)
for reg, voci in per_reg.items():
    with gzip.open(f"{OUT}/{reg}.json.gz", "wt", encoding="utf-8") as fo:
        json.dump({"regione": reg, "anno": 2026, "voci": voci}, fo, ensure_ascii=False, separators=(",", ":"))
    esempi = list(voci.items())[:3]
    print(f"== {reg}: {len(voci)} codici · es. {esempi}", flush=True)
