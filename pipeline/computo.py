"""Analisi del computo metrico estimativo letto dai documenti di gara.

Dal testo (formato PriMus e simili) ricava le voci: codice del prezzario, descrizione, unità, quantità, prezzo, importo.
Poi calcola: prezzario e anno usati, quota di nuovi prezzi (NP), lavorazioni che pesano di più, e, quando abbiamo
il prezzario regionale in vigore, la differenza tra i prezzi del progetto e quelli correnti.
"""
import re
from collections import Counter

NUM = r"\d{1,3}(?:[´'.’]\d{3})*(?:,\d+)?|\d+(?:,\d+)?"
SOMMANO = re.compile(r"SOMMANO\s*\.*\s*(?P<um>[^\d\s][^\s]{0,12})?\s+(?P<n>(?:(?:" + NUM + r")\s+){1,3}(?:" + NUM + r"))\s*$", re.I)
INIZIO = re.compile(r"^\s{0,4}(\d{1,4}(?:\s*/\s*\d{1,4})?)\s{2,}(?=\S)")
CODICE = re.compile(r"^[A-Z0-9][A-Za-z0-9_.\-/]*$")
PREFISSO = re.compile(r"^([A-Z]{2,6})[_.\- ]?(\d{2})(?:[_.\-]|\b)")

REGIONI = {"SAR": "Sardegna", "LOM": "Lombardia", "TOS": "Toscana", "VEN": "Veneto", "VE": "Veneto", "ER": "Emilia-Romagna",
           "RER": "Emilia-Romagna", "EMR": "Emilia-Romagna", "FVG": "Friuli-Venezia Giulia", "FR": "Friuli-Venezia Giulia",
           "PIE": "Piemonte", "LIG": "Liguria", "LAZ": "Lazio", "MAR": "Marche", "UMB": "Umbria", "ABR": "Abruzzo",
           "MOL": "Molise", "CAM": "Campania", "PUG": "Puglia", "BAS": "Basilicata", "CAL": "Calabria", "SIC": "Sicilia",
           "VDA": "Valle d'Aosta", "TN": "Trento", "PAT": "Trento", "BZ": "Bolzano"}


def num(s):
    s = (s or "").replace("´", "").replace("'", "").replace("’", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 1 and len(s.split(".")[-1]) == 3:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def voci(testo):
    """Estrae le voci del computo: una per ogni riga 'SOMMANO'."""
    righe = testo.splitlines()
    out, blocco = [], []
    for r in righe:
        m = SOMMANO.search(r)
        if not m:
            blocco.append(r)
            continue
        numeri = [num(x) for x in re.findall(NUM, m.group("n"))]
        numeri = [x for x in numeri if x is not None]
        if len(numeri) < 2:
            blocco = []
            continue
        qta, prezzo, imp = (numeri[-3], numeri[-2], numeri[-1]) if len(numeri) >= 3 else (numeri[0], None, numeri[-1])
        # codice: frammenti all'inizio delle righe dopo il numero d'ordine
        cod, descr, dentro, ultimo_cod = "", [], False, False
        for b in blocco[-400:]:
            t = b.split()
            m0 = INIZIO.match(b)
            # una riga che inizia con poche cifre subito dopo un pezzo di codice è la coda del codice, non una nuova voce
            if m0 and ultimo_cod and "/" not in m0.group(1) and len(t[0]) <= 3:
                m0 = None
            if m0:
                cod, descr, dentro, ultimo_cod = "", [], True, False
                descr.append(INIZIO.sub("", b, count=0).strip()[:200])
                continue
            if not dentro:
                continue
            if t and not b[:1].isspace() and CODICE.match(t[0]) and (any(ch.isdigit() for ch in t[0]) or "NP" in t[0].upper()):
                cod += t[0]
                descr.append(" ".join(t[1:]))
                ultimo_cod = True
            else:
                descr.append(b.strip())
                if b.strip():
                    ultimo_cod = False
        d = re.sub(r"\s+", " ", " ".join(x for x in descr if x)).strip()
        d = re.sub(r"^\d{1,4}(\s*/\s*\d{1,4})?\s+", "", d)
        out.append({"cod": cod, "descr": d[:160], "um": (m.group("um") or "").strip(), "qta": qta, "prezzo": prezzo, "imp": imp})
        blocco = []
    # scarta righe senza importo plausibile
    return [v for v in out if v["imp"] and v["imp"] > 0]


def prezzario_di(cod):
    m = PREFISSO.match(cod or "")
    if not m:
        return None
    sig, anno = m.group(1), int(m.group(2))
    reg = next((v for k, v in REGIONI.items() if sig.startswith(k)), None)
    return {"sigla": sig + m.group(2), "regione": reg, "anno": 2000 + anno} if reg and 10 <= anno <= 40 else None


def nuovo_prezzo(cod):
    c = (cod or "").upper()
    return bool(re.search(r"(^|[._\-])N\.?P\.?(\d|[._\-]|$)|^NP|AN\.?P", c))


_PREZZARI = {}


def prezzario_corrente(regione):
    """Indice del prezzario regionale in vigore (indici/prezzari/<Regione>.json.gz), se l'abbiamo."""
    if regione not in _PREZZARI:
        import gzip, json, os
        f = os.path.join("indici", "prezzari", f"{regione}.json.gz")
        try:
            _PREZZARI[regione] = json.load(gzip.open(f, "rt"))["voci"] if os.path.exists(f) else None
        except Exception:
            _PREZZARI[regione] = None
    return _PREZZARI[regione]


def chiavi(cod):
    """Possibili forme del codice nel prezzario: senza prefisso regione/anno, con e senza separatori finali."""
    c = (cod or "").upper().replace(" ", "")
    out = [c]
    m = re.match(r"^[A-Z]{2,6}[_.\-]?\d{2,3}[_.\-](.+)$", c)
    if m:
        out.append(m.group(1))
    for x in list(out):
        out.append(x.rstrip(".-_"))
    return list(dict.fromkeys(out))


def confronto(vs, regione):
    """Prezzi del progetto contro il prezzario in vigore, sulle voci con lo stesso codice."""
    P = prezzario_corrente(regione) if regione else None
    if not P:
        return None
    tot_prog = tot_corr = imp = 0.0
    n = 0
    for v in vs:
        if not v.get("prezzo") or not v.get("qta"):
            continue
        k = next((k for k in chiavi(v["cod"]) if k in P), None)
        if not k:
            continue
        pc = P[k][0]
        if not pc or not (0.2 < v["prezzo"] / pc < 5):
            continue
        tot_prog += v["prezzo"] * v["qta"]
        tot_corr += pc * v["qta"]
        imp += v["imp"]
        n += 1
    if n < 3 or not tot_corr:
        return None
    return {"voci": n, "diff": round((tot_prog - tot_corr) / tot_corr * 100, 1), "importo": round(imp, 2)}


_TOKEN = {}
_STOP = {"della", "delle", "degli", "dello", "nella", "nelle", "sulla", "compreso", "compresa", "compresi", "ogni", "altro",
         "opera", "opere", "fornitura", "posa", "lavori", "tipo", "secondo", "dimensioni", "spessore", "quanto", "fino",
         "materiale", "materiali", "eseguito", "eseguita", "realizzato", "realizzata", "mediante", "anche", "come"}


def _tok(t):
    return {w[:6] for w in re.findall(r"[a-zà-ù]{4,}", (t or "").lower()) if w not in _STOP}


def _um(u):
    u = (u or "").lower().replace("²", "2").replace("³", "3").replace(".", "").strip()
    return {"mq": "m2", "mc": "m3", "ml": "m", "cadauno": "cad", "n": "cad", "nr": "cad", "ore": "ora", "h": "ora"}.get(u, u)


def simile(regione, descr, um):
    """Voce del prezzario in vigore più simile per descrizione e unità di misura."""
    P = prezzario_corrente(regione)
    if not P:
        return None
    if regione not in _TOKEN:
        visti, idx = set(), []
        for k, v in P.items():
            key = (v[0], v[2])
            if key in visti:
                continue
            visti.add(key)
            idx.append((k, v[0], _um(v[1]), _tok(v[2]), v[2]))
        _TOKEN[regione] = idx
    q, uq = _tok(descr), _um(um)
    if len(q) < 3:
        return None
    best, bs = None, 0.0
    for k, pr, u, toks, d in _TOKEN[regione]:
        if u != uq or not toks:
            continue
        sc = len(q & toks) / len(q | toks)
        if sc > bs:
            best, bs = (k, pr, d), sc
    return {"cod": best[0], "prezzo": best[1], "descr": best[2], "sim": round(bs, 2)} if best and bs >= 0.45 else None


def controllo_np(vs, regione):
    """Nuovi prezzi confrontati con la voce più simile del prezzario: segnala quelli molto più bassi o più alti."""
    out = []
    np_ = sorted([v for v in vs if nuovo_prezzo(v["cod"]) and v.get("prezzo")], key=lambda v: -v["imp"])[:12]
    for v in np_:
        s = simile(regione, v["descr"], v["um"])
        if not s or not s["prezzo"]:
            continue
        r = v["prezzo"] / s["prezzo"]
        if r < 0.85 or r > 1.25:
            out.append({"descr": v["descr"], "cod": v["cod"], "um": v["um"], "prezzo": v["prezzo"], "imp": v["imp"],
                        "simile": s["descr"], "simile_cod": s["cod"], "simile_prezzo": s["prezzo"], "rapporto": round(r, 2)})
    return out[:5]


def analisi(testo, anno_corrente=2026):
    vs = voci(testo)
    if len(vs) < 3:
        return None
    tot = sum(v["imp"] for v in vs)
    ed = Counter()
    for v in vs:
        p = prezzario_di(v["cod"])
        if p:
            ed[(p["regione"], p["anno"])] += v["imp"]
    np_imp = sum(v["imp"] for v in vs if nuovo_prezzo(v["cod"]))
    top = sorted(vs, key=lambda v: -v["imp"])[:6]
    prez = [{"regione": r, "anno": a, "quota": round(i / tot * 100)} for (r, a), i in ed.most_common(3)]
    vecchio = [p for p in prez if p["anno"] < anno_corrente and p["quota"] >= 20]
    return {
        "voci": len(vs), "totale": round(tot, 2),
        "prezzari": prez,
        "np_quota": round(np_imp / tot * 100) if tot else 0,
        "top": [{"descr": v["descr"], "cod": v["cod"], "um": v["um"], "qta": v["qta"], "prezzo": v["prezzo"],
                 "imp": round(v["imp"], 2), "quota": round(v["imp"] / tot * 100, 1)} for v in top],
        "top3_quota": round(sum(v["imp"] for v in top[:3]) / tot * 100) if tot else 0,
        "prezzi_vecchi": vecchio,
        "confronto": confronto(vs, prez[0]["regione"] if prez else None),
        "np_check": controllo_np(vs, prez[0]["regione"]) if prez else [],
    }


if __name__ == "__main__":
    import gzip, json, sys
    for f in sys.argv[1:]:
        for d in json.load(gzip.open(f, "rt")):
            if d.get("testo"):
                a = analisi(d["testo"])
                print(d["nome"], json.dumps(a, ensure_ascii=False, indent=1)[:2500] if a else "nessuna voce")
