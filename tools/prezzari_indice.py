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
        subprocess.run(["curl", "-fsSL", "-A", UA, "-o", dest, u], timeout=600)

COD = re.compile(r"^[A-Z0-9]{1,7}([._\-/][A-Z0-9]{1,8}){1,9}[.]?$", re.I)
UM = re.compile(r"^(?:1\s+)?(m|m2|m²|mq|m3|m³|mc|ml|kg|t|q|cad|cad\.|n|nr|n\.|a corpo|ora|h|ore|giorno|gg|l|lt|km|dm3|cm|mese|%|kw|cadauno|corpo|mt|tonn)\b", re.I)


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
    cand = [v for v in vals[:8] if v and COD.match(v) and any(ch.isdigit() for ch in v)]
    cod = "|".join(cand) if cand else None
    if not cod:
        return None
    i_um = next((i for i, v in enumerate(vals) if v and len(v) <= 12 and UM.match(v)), None)
    if i_um is None:
        return None
    prezzo = next((numero(v) for v in vals[i_um + 1:] if numero(v) is not None and numero(v) > 0), None)
    if prezzo is None or prezzo > 5_000_000:
        return None
    descr = max((v for v in vals if v and v != cod and not UM.match(v) and numero(v) is None), key=len, default="")
    return cod, prezzo, re.sub(r"^1\s+", "", vals[i_um]), descr[:90]


def pulisci_xml(data):
    """Toglie i riferimenti a caratteri non validi in XML (es. &#1;) che bloccano la lettura."""
    def ok(m):
        v = m.group(1)
        n = int(v[1:], 16) if v[:1] in (b"x", b"X") else int(v)
        return m.group(0) if n in (9, 10, 13) or n >= 32 else b" "
    return re.sub(rb"&#(x?[0-9A-Fa-f]+);", ok, data)


def easy(data):
    """Prezzari nel formato XML 'EASY' (piattaforma di Campania, Piemonte, Sardegna, Toscana):
    <EASY:Articolo codice="..."> ... <EASY:um>..</EASY:um> <EASY:prezzo>553,49</EASY:prezzo> ..."""
    import xml.etree.ElementTree as ET
    out = []
    for ev, el in ET.iterparse(io.BytesIO(pulisci_xml(data)), events=("end",)):
        if el.tag.split("}")[-1] != "Articolo":
            continue
        cod = el.get("codice") or ""
        um = prezzo = None
        descr = ""
        for c in el:
            t = c.tag.split("}")[-1]
            if t == "um":
                um = (c.text or "").strip()
            elif t == "prezzo":
                prezzo = numero(c.text)
            elif t in ("livello3", "livello4", "descrizione") and not descr:
                descr = (c.get("descrizionebreve") or c.text or "").strip()
        if cod and prezzo:
            out.append((cod.upper().rstrip(".-"), prezzo, um or "", re.sub(r"\s+", " ", descr)[:90]))
        el.clear()
    return out


def six(data):
    """Prezzari nello standard XML SIX: <prodotto prdId=...><prdDescrizione breve=.../><prdQuotazione valore=.../></prodotto>."""
    import xml.etree.ElementTree as ET
    um, out = {}, []
    for ev, el in ET.iterparse(io.BytesIO(pulisci_xml(data)), events=("end",)):
        tag = el.tag.split("}")[-1]
        if tag == "unitaDiMisura":
            um[el.get("unitaDiMisuraId")] = el.get("simbolo") or el.get("udmId") or ""
        elif tag == "prodotto":
            q = next((c for c in el if c.tag.split("}")[-1] == "prdQuotazione"), None)
            if q is not None and q.get("valore"):
                d = next((c.get("breve") or c.get("estesa") or "" for c in el if c.tag.split("}")[-1] == "prdDescrizione"), "")
                try:
                    out.append((el.get("prdId", "").upper().rstrip(".-"), float(q.get("valore")), um.get(el.get("unitaDiMisuraId"), ""), d[:90]))
                except ValueError:
                    pass
            el.clear()
    return out


def righe_file(nome, data):
    n = nome.lower()
    if n.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        for f in z.namelist():
            if re.search(r"\.(xlsx|xls|csv|ods|xml)$", f, re.I) and not re.search(r"analisi|confronto|conversione", f, re.I):
                yield from righe_file(f, z.read(f))
        return
    if n.endswith(".xml") or data[:200].lstrip().startswith(b"<"):
        for x in (easy(data) if b"EASY:" in data[:2000] else six(data)):
            yield ("__SIX__",) + x
        return
    if not re.search(r"\.(zip|xlsx|xls|ods|csv|xml)$", n) and data[:2] == b"PK":
        try:
            zipfile.ZipFile(io.BytesIO(data)).getinfo("[Content_Types].xml")
            n += ".xlsx"
        except KeyError:
            n += ".zip"
    if n.endswith(".zip"):
        yield from righe_file(n, data)
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


for vecchio in glob.glob(f"{OUT}/*.json.gz"):
    os.remove(vecchio)
per_reg = {}
for f in sorted(glob.glob(f"{D}/*")):
    b = os.path.basename(f)
    reg = next((r for r in ("Friuli-Venezia Giulia", "Emilia-Romagna", "Valle d'Aosta") if b.startswith(re.sub(r"[^\w.\-]", "_", r))), b.split("_")[0])
    if f.endswith((".pdf", ".bin")):
        continue
    if re.search(r"analisi|confronto|brevi|transcodifica|Allegato_D", f, re.I) or os.path.getsize(f) < 100_000:
        continue
    try:
        data = open(f, "rb").read()
        n = 0
        for r in righe_file(f, data):
            x = tuple(r[1:]) if r and r[0] == "__SIX__" else da_riga(list(r))
            if x:
                for c in x[0].split("|"):
                    c = c.upper().replace(" ", "").rstrip(".-")
                    for k in {c, re.sub(r"^[A-Z]{2,6}[_.\-]?\d{2,3}[_.\-]", "", c)}:
                        per_reg.setdefault(reg, {})[k] = [x[1], x[2], x[3]]
                n += 1
        print(f"{reg:24} {os.path.basename(f)[:60]:60} voci {n}", flush=True)
    except Exception as e:
        print(f"{reg:24} {os.path.basename(f)[:60]:60} ERRORE {type(e).__name__}: {str(e)[:120]}", flush=True)
ANNO = {"Sicilia": 2024, "Lazio": 2023, "Umbria": 2025}   # prezzari prorogati, ancora in vigore nel 2026
for reg, voci in per_reg.items():
    buone = sum(1 for k, v in voci.items() if v[2] and not re.fullmatch(r"[\d.]+", k))
    if buone < 1000:
        print(f"== {reg}: scartato, solo {buone} voci leggibili", flush=True)
        continue
    with gzip.open(f"{OUT}/{reg}.json.gz", "wt", encoding="utf-8") as fo:
        json.dump({"regione": reg, "anno": ANNO.get(reg, 2026), "voci": voci}, fo, ensure_ascii=False, separators=(",", ":"))
    esempi = list(voci.items())[:3]
    print(f"== {reg}: {len(voci)} codici · es. {esempi}", flush=True)
