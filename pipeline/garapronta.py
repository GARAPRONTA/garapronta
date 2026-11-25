#!/usr/bin/env python3
"""GaraPronta — pipeline giornaliera.

1. Scarica TUTTI gli avvisi pubblicati ieri sulla Piattaforma di pubblicità legale ANAC.
2. Salva un estratto compatto in data/AAAA/MM/GG.json.gz (lo storico è nostro).
3. Legge gli iscritti dalla lista Brevo "Prova Gratuita".
4. Per ogni iscritto sceglie: bandi di lavori, indagini di mercato ("cerchiamo imprese da invitare"),
   elenchi di imprese aperti, e il riepilogo degli affidamenti diretti nella sua regione.
5. Invia l'email tramite Brevo. In modalità prova (default) scrive SOLO agli indirizzi con "+test".

Variabili d'ambiente: BREVO_API_KEY (secret), BREVO_LIST_ID (default 5),
DATA (gg/mm/aaaa, default ieri), LIVE=1 per inviare a tutti, DRY=1 per non inviare nulla.
"""
import re
import gzip, html, json, os, sys, time, urllib.parse, urllib.request, urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ANAC = "https://pubblicitalegale.anticorruzione.it/api/v0/avvisi"
BREVO = "https://api.brevo.com/v3"
SITE = "https://garapronta.github.io/garapronta/"
SENDER = {"name": "GaraPronta", "email": "garapronta@gmail.com"}

NUTS_REGIONE = {
    "ITC1": "Piemonte", "ITC2": "Valle d'Aosta", "ITC3": "Liguria", "ITC4": "Lombardia",
    "ITH1": "Trentino-Alto Adige", "ITH2": "Trentino-Alto Adige", "ITH3": "Veneto",
    "ITH4": "Friuli-Venezia Giulia", "ITH5": "Emilia-Romagna", "ITI1": "Toscana", "ITI2": "Umbria",
    "ITI3": "Marche", "ITI4": "Lazio", "ITF1": "Abruzzo", "ITF2": "Molise", "ITF3": "Campania",
    "ITF4": "Puglia", "ITF5": "Basilicata", "ITF6": "Calabria", "ITG1": "Sicilia", "ITG2": "Sardegna",
}
# Ribassi mediani vincenti misurati su 3.730 esiti di lavori (60 giorni a nov. 2026).
RIBASSO = {"OG 1": 13.0, "OG 3": 14.6, "OG 8": 19.2}
RIBASSO_TUTTI = 14.7


# ---------------------------------------------------------------- utilità
def http_json(url, data=None, headers=None, method=None, tries=4):
    h = {"accept": "application/json", "user-agent": "Mozilla/5.0 GaraPronta"}
    h.update(headers or {})
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        h["content-type"] = "application/json"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == tries - 1:
                raise RuntimeError(f"HTTP {e.code} su {url.split('?')[0]}: {e.read()[:300]!r}")
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))


def sezione(tmpl, lettera):
    for s in tmpl.get("sections") or []:
        if (s.get("name") or "").startswith(f"SEZ. {lettera}"):
            return s
    return {}


def trova(obj, chiave):
    """Primo valore di `chiave` ovunque dentro obj."""
    if isinstance(obj, dict):
        if chiave in obj and obj[chiave] not in (None, "", []):
            return obj[chiave]
        for v in obj.values():
            r = trova(v, chiave)
            if r not in (None, "", []):
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = trova(v, chiave)
            if r not in (None, "", []):
                return r
    return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def euro(v):
    if v is None:
        return "importo n.d."
    return f"{v:,.0f} €".replace(",", ".")


def pulisci(t):
    return html.unescape(" ".join((t or "").split()))


def ente_bello(t):
    t = pulisci(t)
    if t.isupper():
        piccole = {"di", "del", "della", "dei", "delle", "e", "per", "la", "il", "lo", "d'"}
        t = " ".join(w.lower() if w.lower() in piccole else w.capitalize() for w in t.split())
        t = t[:1].upper() + t[1:]
    return t


# ---------------------------------------------------------------- 1. ANAC
def scarica(giorno):
    out, page = [], 0
    while True:
        u = f"{ANAC}?dataPubblicazioneStart={giorno}&dataPubblicazioneEnd={giorno}&page={page}&size=100"
        j = http_json(u)
        out += j.get("content") or []
        if j.get("last") or not j.get("content"):
            break
        page += 1
        time.sleep(0.2)
    return out


def estrai(a):
    t = ((a.get("templates") or [{}])[0] or {}).get("template") or {}
    A, B, C = sezione(t, "A"), sezione(t, "B"), sezione(t, "C")
    items = []
    for it in C.get("items") or []:
        nuts = it.get("luogo_nuts") or trova(it, "luogo_nuts") or ""
        if isinstance(nuts, list):
            nuts = nuts[0] if nuts else ""
        aggi = []
        for g in (it.get("aggiudicatari") or []) + (it.get("aggiudicatari_ad") or []):
            for s in g.get("soggetti") or []:
                aggi.append({"nome": s.get("denominazione"), "cf": s.get("codice_fiscale")})
        items.append({
            "cig": it.get("cig"),
            "natura": it.get("natura_principale"),
            "descr": pulisci(it.get("descrizione"))[:1200],
            "cpv": trova(it.get("cpv"), "codice") if isinstance(it.get("cpv"), (list, dict)) else it.get("cpv"),
            "valore": num(it.get("valore_complessivo_stimato")) or num(it.get("valore_affidamento")),
            "vincente": num(it.get("valore_offerta_vincente")),
            "nuts": nuts if isinstance(nuts, str) else str(nuts),
            "istat": it.get("luogo_istat"),
            "cat": [c.get("codice") for c in (it.get("categorie") or []) if isinstance(c, dict) and c.get("codice")],
            "scadenza": it.get("termine_ricezione"),
            "criterio": trova(it.get("criteri_aggiudicazione"), "criterio") or None,
            "aggiudicatari": aggi,
        })
    return {
        "id": a.get("idAvviso"), "appalto": a.get("idAppalto"),
        "tipologia": a.get("tipologia"), "scheda": a.get("codiceScheda"), "tipo": a.get("tipo"),
        "pubblicato": a.get("dataPubblicazione"), "scadenza": a.get("dataScadenza"),
        "titolo": pulisci((t.get("metadata") or {}).get("titolo"))[:1200],
        "ente": ente_bello(trova(A, "denominazione_amministrazione") or ""),
        "procedura": trova(B, "tipo_procedura_aggiudicazione"),
        "link": trova(B, "documenti_di_gara_link") or trova(C, "documenti_di_gara_link"),
        "items": items,
    }


def salva(giorno, avvisi):
    d = datetime.strptime(giorno, "%d/%m/%Y")
    path = f"data/{d:%Y/%m/%d}.json.gz"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(avvisi, f, ensure_ascii=False, separators=(",", ":"))
    return path


# ---------------------------------------------------------------- 2. iscritti
CLASSI = {"I": 258_000, "II": 516_000, "III": 1_033_000, "III-BIS": 1_500_000, "IV": 2_582_000, "IV-BIS": 3_500_000,
          "V": 5_165_000, "VI": 10_329_000, "VII": 15_494_000, "VIII": 10**12}
CONFINANTI = {
    "Piemonte": ["Valle d'Aosta", "Lombardia", "Liguria", "Emilia-Romagna"], "Valle d'Aosta": ["Piemonte"],
    "Lombardia": ["Piemonte", "Emilia-Romagna", "Veneto", "Trentino-Alto Adige"], "Trentino-Alto Adige": ["Lombardia", "Veneto"],
    "Veneto": ["Lombardia", "Trentino-Alto Adige", "Friuli-Venezia Giulia", "Emilia-Romagna"], "Friuli-Venezia Giulia": ["Veneto"],
    "Liguria": ["Piemonte", "Emilia-Romagna", "Toscana"], "Emilia-Romagna": ["Lombardia", "Veneto", "Toscana", "Marche", "Liguria", "Piemonte"],
    "Toscana": ["Liguria", "Emilia-Romagna", "Umbria", "Marche", "Lazio"], "Umbria": ["Toscana", "Marche", "Lazio"],
    "Marche": ["Emilia-Romagna", "Toscana", "Umbria", "Lazio", "Abruzzo"], "Lazio": ["Toscana", "Umbria", "Marche", "Abruzzo", "Molise", "Campania"],
    "Abruzzo": ["Marche", "Lazio", "Molise"], "Molise": ["Abruzzo", "Lazio", "Campania", "Puglia"],
    "Campania": ["Lazio", "Molise", "Puglia", "Basilicata"], "Puglia": ["Molise", "Campania", "Basilicata"],
    "Basilicata": ["Campania", "Puglia", "Calabria"], "Calabria": ["Basilicata", "Sicilia"], "Sicilia": ["Calabria"], "Sardegna": [],
}


def leggi_soa(testo):
    """'OG8-III, OS21, OS 12-B' -> (['OG 8', 'OS 21', 'OS 12-B'], {'OG 8': 'III'})"""
    cats, classi = [], {}
    for pezzo in re.split(r"[,;/]+", testo or ""):
        t = pezzo.strip().upper().replace(" ", "")
        m = re.match(r"^(OG|OS)(\d{1,2})(-?[AB])?(?:[-\s]*(VIII|VII|VI|V|IV-?BIS|IV|III-?BIS|III|II|I))?$", t)
        if not m:
            if t == "ALTRA":
                cats.append("ALTRA")
            continue
        c = f"{m.group(1)} {int(m.group(2))}" + (("-" + m.group(3).strip("-")) if m.group(3) else "")
        cats.append(c)
        if m.group(4):
            classi[c] = m.group(4).replace("BIS", "-BIS").replace("--", "-")
    return cats, classi


def iscritti(key, lista):
    out, off = [], 0
    while True:
        j = http_json(f"{BREVO}/contacts/lists/{lista}/contacts?limit=500&offset={off}", headers={"api-key": key})
        cs = j.get("contacts") or []
        for c in cs:
            at = c.get("attributes") or {}
            soa, classi = leggi_soa(at.get("SOA") or "")
            out.append({"email": c["email"], "soa": soa, "classi": classi, "regione": (at.get("REGIONE") or "Tutta Italia").strip(),
                        "settore": (at.get("SETTORE") or "Lavori edili").strip(),
                        "enti": [x for x in (at.get("ENTI") or "").split(",") if x.strip()],
                        "no_enti": [x for x in (at.get("ENTI_NO") or "").split(",") if x.strip()]})
        if len(cs) < 500:
            break
        off += 500
    return out


# ---------------------------------------------------------------- 3. scelta gare
_COMUNI = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "comuni_regioni.json")))


def _norm(t):
    import unicodedata, re
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()


def regione(it):
    n = str(it.get("nuts") or "")
    if n[:4] in NUTS_REGIONE:
        return NUTS_REGIONE[n[:4]]
    for campo in (it.get("istat"), n):
        if campo and _norm(campo) in _COMUNI:
            return _COMUNI[_norm(campo)]
    return None


def per_iscritto(avvisi, u):
    tutta = u["regione"].lower() in ("tutta italia", "")
    soa = set(u["soa"])
    altro = "ALTRA" in soa or not soa
    vicine = set(CONFINANTI.get(u["regione"], []))

    def zona(it):
        if tutta:
            return "dentro"
        r = regione(it)
        return "dentro" if r == u["regione"] else ("vicina" if r in vicine else None)

    def cat_ok(it):
        return altro or not it["cat"] or soa & set(it["cat"])

    bandi, indagini, elenchi, diretti, esiti, cercano = [], [], [], [], [], []
    for a in avvisi:
        if a["tipo"] != "avviso":
            continue
        for it in a["items"]:
            if (it.get("natura") or "").lower() != "lavori" and a["tipologia"] != "ELENCHI_OPERATORI_ECONOMICI":
                continue
            z = zona(it)
            riga = (a, it)
            # "cercano te": la tua categoria è tra le secondarie di una gara la cui prevalente non hai (anche fuori zona)
            if (a["tipologia"] in ("BANDI", "INDAGINI_DI_MERCATO_SOTTO_SOGLIA") and not altro and it.get("cat")
                    and prevalente(it) not in soa and soa & set(it["cat"]) and z in ("dentro", "vicina")):
                cercano.append(riga)
                continue
            if not z:
                continue
            it["_zona"] = z
            if a["tipologia"] == "BANDI" and cat_ok(it):
                bandi.append(riga)
            elif a["tipologia"] == "INDAGINI_DI_MERCATO_SOTTO_SOGLIA" and cat_ok(it):
                indagini.append(riga)
            elif a["tipologia"] == "ELENCHI_OPERATORI_ECONOMICI" and z == "dentro":
                elenchi.append(riga)
            elif a["tipologia"] == "AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA" and z == "dentro":
                diretti.append(riga)
            elif a["tipologia"] == "RISULTATI" and it.get("aggiudicatari") and cat_ok(it) and z == "dentro":
                esiti.append(riga)
    oggi = datetime.now(timezone.utc).date()

    def aperta(r):
        a, it = r
        s = it.get("scadenza") or a.get("scadenza")
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date() >= oggi
        except Exception:
            return True
    key = lambda r: (0 if r[1].get("_zona") == "dentro" else 1, -(r[1].get("valore") or 0))
    bandi = [r for r in bandi if aperta(r)]
    indagini = [r for r in indagini if aperta(r)]
    # le regioni vicine entrano solo se nella tua regione oggi c'è poco (sotto le 5 occasioni)
    if len([r for r in bandi + indagini if r[1].get("_zona") == "dentro"]) >= 5:
        bandi = [r for r in bandi if r[1].get("_zona") == "dentro"]
        indagini = [r for r in indagini if r[1].get("_zona") == "dentro"]
    PER_ISCRITTO_EXTRA["esiti"] = sorted(esiti, key=key)
    PER_ISCRITTO_EXTRA["cercano"] = sorted([r for r in cercano if aperta(r)], key=key)[:6]
    PER_ISCRITTO_EXTRA["classi"] = u.get("classi") or {}
    PER_ISCRITTO_EXTRA["mov"] = movimenti_enti(avvisi, u)
    PER_ISCRITTO_EXTRA["seguiti"] = set(seguiti(u))
    # affidamenti diretti: prima quelli delle sue categorie, poi i più grandi
    PER_ISCRITTO_EXTRA["diretti_top"] = sorted(
        [r for r in diretti if r[1].get("aggiudicatari")],
        key=lambda r: (0 if (r[1]["cat"] and not altro and soa & set(r[1]["cat"])) else 1, -(r[1].get("valore") or 0)))
    return sorted(bandi, key=key), sorted(indagini, key=key), elenchi[:5], diretti


PER_ISCRITTO_EXTRA = {}

# Imprese che hanno chiesto di non comparire (codice fiscale/P.IVA o nome, uno per riga)
try:
    RIMOZIONI = {l.strip().upper() for l in open(os.path.join(os.path.dirname(__file__), "rimozioni.txt"), encoding="utf-8")
                 if l.strip() and not l.startswith("#")}
except FileNotFoundError:
    RIMOZIONI = set()


def imprese(it):
    """Nomi degli aggiudicatari, tranne chi ha chiesto la rimozione."""
    out = []
    for g in it.get("aggiudicatari") or []:
        nome, cf = (g.get("nome") or "").strip(), (g.get("cf") or "").strip().upper()
        if not nome:
            continue
        out.append("Impresa (dato rimosso su richiesta)" if cf in RIMOZIONI or nome.upper() in RIMOZIONI else nome)
    return out


def ribasso(it):
    v, w = it.get("valore"), it.get("vincente")
    if v and w and 0 < w < v:
        r = (v - w) / v * 100
        return round(r, 1) if r < 60 else None
    return None


RESOCONTI = {}

# ---------------------------------------------------------------- 4. email
# Stile del sito: sfondo #f5f5f7, accento blu iPhone #007aff, schede bianche arrotondate.
BLU, INK, INK2, INK3 = "#007aff", "#1d1d1f", "#6e6e73", "#86868b"
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Helvetica,Arial,sans-serif"


def pill(testo, fg, bg):
    return (f'<span style="display:inline-block;background:{bg};color:{fg};border-radius:999px;'
            f'padding:5px 11px;font-size:12px;font-weight:600;line-height:1">{testo}</span>')


def giorni_a(s):
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d, (d.date() - datetime.now(timezone.utc).date()).days
    except Exception:
        return None, None


def scad_pill(s):
    d, gg = giorni_a(s) if s else (None, None)
    if d is None:
        return ""
    if gg <= 7:
        return pill(f"⏱ {gg} giorni · {d:%d/%m}", "#c2410c", "#fdeee6")
    return pill(f"Scade il {d:%d/%m} · {gg} gg", INK, "#f0f0f3")


def frase(t):
    t = t or ""
    if sum(ch.isupper() for ch in t) > 0.6 * max(1, sum(ch.isalpha() for ch in t)):
        t = t.lower().capitalize()
    return t


_PREFISSI = re.compile(
    r"^\s*(?:(?:procedura|gara)\s+(?:aperta|negoziata|ristretta|telematica)[^:]*?(?:per|relativa a|avente ad oggetto)\s+)?"
    r"(?:l['’]\s*)?(?:affidamento|appalto|esecuzione|realizzazione)?\s*(?:dei|degli|del|delle|di)?\s*"
    r"(?:lavori|opere|intervent[io])\s+(?:di|per|relativ[io] a)\s+", re.I)
_CODICI = re.compile(r"\s*[-–,;(]?\s*\b(?:CIG|CUP)\b\s*[:n.°]*\s*[A-Z0-9]{10,15}\)?", re.I)


def pulito(t):
    """Oggetto della gara leggibile e completo: niente maiuscolo urlato, niente formule burocratiche, niente CIG/CUP."""
    t = (t or "").replace('\\"', '"').replace("\\", "")
    t = re.sub(r"\s+", " ", _CODICI.sub("", t)).strip(" .-–:;\"'“”_")
    t = frase(t)
    r = _PREFISSI.sub("", t, count=1).strip(" .-–:;\"'“”_")
    if len(r) > 12:
        t = r[0].upper() + r[1:]
    # nomi propri dopo via/viale/piazza…: "viale giulio cesare" -> "viale Giulio Cesare"
    stop = r"(?:e|ed|di|del|della|dello|dei|degli|delle|nel|nella|in|a|al|alla|per|con|tra|da|anno|lotto|importo|cig|cup)\b"
    nome = r"(?!" + stop + r")[a-zà-ù'’]+"
    return re.sub(r"\b(via|viale|piazza|piazzale|corso|largo|vicolo|località|loc\.|frazione di|frazione|comune di)\s+(" + nome + r"(?: (?:" + nome + r"|della|delle|del|di)){0,3})",
                  lambda m: m.group(1) + " " + " ".join(w if re.fullmatch(stop, w) else w[:1].upper() + w[1:] for w in m.group(2).split(" ")),
                  t, flags=re.I)


# ---------------------------------------------------------------- motore "quanto offrire" (banca dati ANAC)
_IND = {}


def _indici():
    if "r" not in _IND:
        try:
            _IND["r"] = json.load(gzip.open("indici/ribassi.json.gz", "rt"))
            _IND["e"] = json.load(gzip.open("indici/enti.json.gz", "rt"))
        except Exception:
            _IND["r"], _IND["e"] = {}, {}
    return _IND["r"], _IND["e"]


def _nome(s):
    s = (s or "").upper().replace("'", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


SOCIETA = re.compile(r"\b(S\.?\s?R\.?\s?L|S\.?\s?P\.?\s?A|S\.?\s?N\.?\s?C|S\.?\s?A\.?\s?S|SOC\.?|SOCIETA|COOP|CONSORZIO|CONSORTILE|S\.?C\.?A\.?R\.?L|SCARL|S\.?C\.?R\.?L|GROUP|SPA|SRL|SRLS|S\.?R\.?L\.?S|ONLUS|FONDAZIONE|ASSOCIAZIONE|RTI|ATI)\b", re.I)


def pubblico(nome):
    """Nomi delle imprese nelle pagine web: tutti, tranne chi ha chiesto la rimozione."""
    parti = [x.strip() for x in (nome or "").split("+")]
    return " + ".join("Impresa (dato rimosso su richiesta)" if x.upper() in RIMOZIONI else x for x in parti if x)


FASCE = [(150_000, "f1", "sotto i 150.000 €"), (1_000_000, "f2", "tra 150.000 € e 1 milione"),
         (5_382_000, "f3", "tra 1 e 5,4 milioni"), (10**12, "f4", "sopra la soglia europea")]


def fascia(v):
    for lim, k, txt in FASCE:
        if (v or 0) < lim:
            return k, txt
    return "f4", FASCE[-1][2]


def criterio(it):
    """Prezzo più basso o offerta economicamente più vantaggiosa: dall'avviso o, se c'è, dal resoconto dei documenti."""
    testi = [it.get("criterio") or ""]
    res = RESOCONTI.get(it.get("cig") or "") or {}
    testi += [p.get("v", "") for p in res.get("punti") or [] if (p.get("t") or "").lower().startswith("criterio")]
    t = " ".join(testi).lower()
    if re.search(r"prezzo pi[uù] basso|minor prezzo|massimo ribasso", t):
        return "prezzo"
    if re.search(r"vantaggios|oepv|qualit[aà]/prezzo|punteggio tecnico", t):
        return "oepv"
    return None


def _reg_anac(it):
    R, _ = _indici()
    k = _nome(regione(it) or "").replace(" ", "")
    return [x for x in (R.get("regione") or {}) if _nome(x).replace(" ", "") == k or ("TRENTINO" in k and ("TRENTO" in x or "BOLZANO" in x))]


def storico(a, it):
    """Ribassi vincenti in gare SIMILI: stessa categoria prevalente, stessa fascia d'importo e stesso criterio.
    Si parte dalla zona più stretta (stesso ente) e si allarga a provincia, regione, Italia solo se i casi sono pochi."""
    R, E = _indici()
    if not R:
        return None
    pv = prevalente(it)
    if not pv:
        return None
    c = pv.replace(" ", "")
    S = R.get("simili") or {}
    ente = E.get(_nome(a.get("ente")))
    cf, prov = (ente or {}).get("cf"), (ente or {}).get("prov")
    regs = _reg_anac(it)
    f, ftxt = fascia(it.get("valore"))
    cr = criterio(it)
    crtxt = {"prezzo": "al prezzo più basso", "oepv": "con offerta economicamente più vantaggiosa"}.get(cr, "")
    tentativi = []
    for sig, k, zona in [("E", cf, a.get("ente")), ("P", prov, f"in provincia di {titolo_ente(prov or '')}"),
                         *[("R", r, f"in {regione(it)}") for r in regs[:1]], ("I", "IT", "in Italia")]:
        if not k:
            continue
        if cr:
            tentativi.append((f"{sig}|{k}|{c}|{f}|{cr}", sig, zona, True, True))
        tentativi.append((f"{sig}|{k}|{c}|{f}", sig, zona, True, False))
    # stesso ente anche senza fascia, prima di allargare alla regione
    if cf:
        tentativi.insert(2 if cr else 1, (f"E|{cf}|{c}", "E", a.get("ente"), False, False))
    for chiave, sig, zona, con_f, con_c in tentativi:
        x = S.get(chiave)
        if x and x["n"] >= 6:
            liv = {"E": "ente", "P": "provincia", "R": "regione", "I": "italia"}[sig]
            descr = f"{x['n']} gare {c}" + (f" {ftxt}" if con_f else "") + (f" {crtxt}" if con_c else "") + f" {'di ' + zona if sig == 'E' else zona}"
            ult = x.get("ultime") or (S.get(f"E|{cf}|{c}") or {}).get("ultime") or []
            return {**x, "ultime": ult, "livello": liv, "dove": zona, "cat": c, "descr": descr.strip()}
    # vecchio indice come ultima risorsa
    s0 = (R.get("ente", {}).get(cf, {}).get(c) if cf else None)
    if s0 and s0["n"] >= 3:
        return {**s0, "livello": "ente", "dove": a.get("ente"), "cat": c, "descr": f"{s0['n']} gare {c} di {a.get('ente')}"}
    return None


# ---------------------------------------------------------------- mappa degli enti bersaglio
MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_PICCOLE = {"di", "del", "della", "dei", "degli", "delle", "e", "per", "la", "il", "lo", "le", "in", "a", "al", "alla", "da", "d", "l"}
_SIGLE = {"ULSS", "ASL", "ATER", "ASP", "AUSL", "ASST", "ATS", "ANAS", "RFI", "ARPA", "INPS", "INAIL", "ATC", "ACER", "IACP", "ASM", "AMA", "ASL", "SPA", "SRL"}


def titolo_ente(s):
    out = []
    for i, w in enumerate((s or "").split()):
        lw = w.lower()
        if w.upper() in _SIGLE or (len(w) <= 4 and "." in w):
            out.append(w.upper())
        elif i and lw in _PICCOLE:
            out.append(lw)
        else:
            out.append("'".join(x[:1].upper() + x[1:] for x in lw.split("'")))
    return " ".join(out)


def _web():
    if "w" not in _IND:
        try:
            _IND["w"] = json.load(gzip.open("indici/enti_web.json.gz", "rt"))
        except Exception:
            _IND["w"] = {}
        try:
            _IND["m"] = json.load(gzip.open("indici/mappa_enti.json.gz", "rt"))["regioni"]
        except Exception:
            _IND["m"] = {}
    return _IND["w"], _IND["m"]


def enti_bersaglio(reg, cats, n=40):
    """Enti della regione che affidano lavori delle categorie date senza bando (diretti o su invito)."""
    W, M = _web()
    k = _nome(reg).replace(" ", "")
    chiavi = [x for x in M if _nome(x).replace(" ", "") == k]
    if "TRENTINO" in k:
        chiavi = [x for x in M if "TRENTO" in x or "BOLZANO" in x]
    tot = {}
    for ch in chiavi:
        for c in cats:
            for e in M[ch].get(c.replace(" ", ""), []):
                t = tot.setdefault(e["cf"], {**e, "cats": [], "dir": 0, "neg": 0, "val": 0, "imp": 0, "conv": 0, "top": 0})
                t["cats"].append(c.replace(" ", ""))
                for f in ("dir", "neg", "val", "imp", "conv"):
                    t[f] += e.get(f) or 0
                t["top"] = max(t["top"], e.get("top") or 0)
    out = sorted(tot.values(), key=lambda e: -(e["dir"] + e["neg"]))[:n]
    for e in out:
        w = W.get(_nome(e["ente"])) or {}
        e["piatt"], e["elenchi"] = w.get("piatt"), w.get("elenchi") or []
    return out


def frase_rotazione(e):
    if not e.get("conv"):
        return ""
    quota = (e.get("top") or 0) / e["conv"]
    if quota >= 0.4:
        return f"un'impresa ha preso il {round(quota * 100)}% dei lavori"
    return f"{e['imp']} imprese diverse, nessuna domina" if quota < 0.2 else f"{e['imp']} imprese diverse"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def url_mappa(reg, cats):
    return f"{SITE}g/enti/{slug(reg)}-{slug('-'.join(c.replace(' ', '') for c in cats) or 'tutte')}.html"


def sezione_enti(u):
    """Blocco email: gli enti della tua regione che affidano i tuoi lavori senza bando."""
    reg = u["regione"]
    if reg.lower() in ("tutta italia", ""):
        return ""
    cats = [c for c in u["soa"] if c != "ALTRA"][:4] or ["OG 1", "OG 3"]
    enti = enti_bersaglio(reg, cats, 5)
    if not enti:
        return ""
    righe = ""
    for e in enti:
        extra = []
        if e["elenchi"]:
            extra.append(f'<a href="{html.escape(e["elenchi"][0]["link"] or SITE)}" style="color:#1f9d55;font-weight:600;text-decoration:none">Elenco imprese ›</a>')
        if e["piatt"]:
            extra.append(f'<a href="{html.escape(e["piatt"])}" style="color:{BLU};font-weight:600;text-decoration:none">Piattaforma gare ›</a>')
        extra.append(f'<a href="{html.escape(url_segui(e["cf"], e["ente"], off=True))}" style="color:{INK3};text-decoration:none">Non seguire</a>')
        mese = f" · più attivo a {MESI_IT[int(e['mese']) - 1]}" if e.get("mese") else ""
        righe += f"""<tr><td style="padding:12px 0;border-top:1px solid #f0f0f3">
<div style="font-size:14px;font-weight:650;color:{INK}">{html.escape(titolo_ente(e['ente']))} <span style="font-weight:400;color:{INK3};font-size:12px">{html.escape(titolo_ente(e.get('prov') or ''))}</span></div>
<div style="font-size:13px;color:{INK2};margin-top:3px">{e['dir'] + e['neg']} lavori senza bando in 3 anni ({e['dir']} diretti, {e['neg']} su invito) · {html.escape(frase_rotazione(e))}{mese}</div>
<div style="font-size:13px;margin-top:5px">{' &nbsp;·&nbsp; '.join(extra)}</div></td></tr>"""
    return titolo_sezione("Enti da conoscere", "Chi affida i tuoi lavori senza bando",
                          f"{', '.join(c.replace(' ', '') for c in cats)} in {reg}, ultimi 3 anni. Farsi conoscere da questi enti è la strada per essere invitati.") + f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:4px 22px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe}</table>
<div style="font-size:12px;color:{INK2};margin-top:10px;line-height:1.45">Segui già i 15 enti principali della tua zona: ogni mattina ti diciamo cosa hanno fatto. Vuoi seguirne altri? Aprili dalla mappa completa.</div>
<div style="margin-top:10px"><a href="{url_mappa(reg, cats)}" style="font-size:14px;font-weight:600;color:{BLU};text-decoration:none">▸ Vedi tutti gli enti della tua zona</a></div>
</td></tr></table>"""


def pagina_mappa(reg, cats):
    enti = enti_bersaglio(reg, cats, 40)
    e = html.escape
    cs = ", ".join(c.replace(" ", "") for c in cats)
    righe = "".join(f"""<tr><td><b>{e(titolo_ente(x['ente']))}</b><small>{e(titolo_ente(x.get('prov') or ''))}</small></td>
<td style="text-align:right"><b>{x['dir'] + x['neg']}</b><small>{x['dir']} diretti · {x['neg']} su invito</small></td>
<td style="text-align:right">{euro(x['val']) if x.get('val') else '—'}</td>
<td>{e(frase_rotazione(x))}{('<small>più attivo a ' + MESI_IT[int(x['mese']) - 1] + '</small>') if x.get('mese') else ''}</td>
<td>{('<a href="' + e(x['elenchi'][0]['link'] or SITE) + '">Elenco imprese</a><br>') if x['elenchi'] else ''}{('<a href="' + e(x['piatt']) + '">Piattaforma gare</a>') if x['piatt'] else ''}</td></tr>""" for x in enti)
    return f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enti che affidano lavori {e(cs)} in {e(reg)} · GaraPronta</title><meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&display=swap" rel="stylesheet">
<style>body{{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1d1d1f;background:#f5f5f7;line-height:1.5}}
.w{{max-width:980px;margin:0 auto;padding:0 18px 50px}} header{{padding:22px 0}} header a{{font-weight:650;color:#1d1d1f;text-decoration:none}}
.card{{background:#fff;border:1px solid #e5e5ea;border-radius:26px;padding:26px;margin-bottom:16px;overflow-x:auto}} h1{{font-size:30px;letter-spacing:-.03em;line-height:1.15;margin:0 0 8px}}
p{{color:#6e6e73;margin:0 0 6px}} table{{width:100%;border-collapse:collapse;min-width:720px}} th{{text-align:left;font-size:12px;color:#86868b;font-weight:500;padding:8px 10px 8px 0}}
td{{font-size:14px;padding:11px 10px 11px 0;border-top:1px solid #f0f0f3;vertical-align:top}} small{{display:block;color:#86868b;font-size:12px}} a{{color:#007aff;font-weight:600;text-decoration:none}}
.f{{font-size:12px;color:#86868b;text-align:center}}</style></head><body><div class="w">
<header><a href="{SITE}">● GaraPronta</a></header>
<div class="card"><h1>Chi affida lavori {e(cs)} senza bando in {e(reg)}</h1>
<p>Gli enti che negli ultimi 3 anni hanno affidato più lavori di queste categorie con affidamento diretto o con procedura negoziata su invito. Sotto i 150.000 € l'ente sceglie l'impresa e deve ruotare gli inviti: iscriversi ai loro elenchi e alle loro piattaforme è il modo per essere chiamati.</p></div>
<div class="card"><table><tr><th>Ente</th><th style="text-align:right">Lavori senza bando</th><th style="text-align:right">Valore</th><th>Rotazione</th><th>Dove iscriversi</th></tr>{righe}</table></div>
<p class="f">Fonte: Banca dati nazionale dei contratti pubblici (ANAC, CC BY-SA 4.0), anni 2023-2025, e avvisi della Piattaforma di pubblicità legale ANAC. · <a href="{SITE}privacy.html" style="color:#86868b;font-weight:400">Privacy</a></p>
</div></body></html>"""


def scrivi_mappe(utenti):
    os.makedirs("g/enti", exist_ok=True)
    fatti = set()
    for u in utenti:
        reg = u["regione"]
        if reg.lower() in ("tutta italia", ""):
            continue
        cats = [c for c in u["soa"] if c != "ALTRA"][:4] or ["OG 1", "OG 3"]
        path = url_mappa(reg, cats).replace(SITE, "")
        if path not in fatti:
            with open(path, "w", encoding="utf-8") as f:
                f.write(pagina_mappa(reg, cats))
            fatti.add(path)
    return len(fatti)


# ---------------------------------------------------------------- trova partner (attestazioni SOA ANAC)
def _partner_idx():
    if "p" not in _IND:
        try:
            _IND["p"] = json.load(gzip.open("indici/partner.json.gz", "rt"))["province"]
        except Exception:
            _IND["p"] = {}
    return _IND["p"]


def prevalente(it):
    """Categoria prevalente: nei dati PVL l'ordine non è garantito; le OG sono quasi sempre la prevalente."""
    cats = it.get("cat") or []
    return next((c for c in cats if c.replace(" ", "").startswith("OG")), cats[0] if cats else None)


def provincia_ente(a):
    R, E = _indici()
    e = E.get(_nome(a.get("ente")))
    return e["prov"] if e else None


def partner_per(a, cat, n=5):
    """Imprese con SOA valida nella categoria, nella provincia dell'ente (poi nella regione), ordinate per gare vinte."""
    P = _partner_idx()
    c = cat.replace(" ", "")
    prov = provincia_ente(a)
    out = list((P.get(prov) or {}).get(c, [])) if prov else []
    if len(out) < n and prov:
        reg = _COMUNI.get(_norm(prov))
        altri = [x for pv, cats in P.items() if pv != prov and _COMUNI.get(_norm(pv)) == reg for x in cats.get(c, [])]
        out += sorted(altri, key=lambda x: (-x["vc"], -x["v"]))
    out = [x for x in out if (x.get("cf") or "").upper() not in RIMOZIONI and (x.get("nome") or "").upper() not in RIMOZIONI]
    return out[:n], prov


# ---------------------------------------------------------------- segui i tuoi enti
def url_segui(cf, nome, off=False):
    from urllib.parse import quote
    return f"{SITE}segui.html?{'off' if off else 'cf'}={cf}&n={quote(titolo_ente(nome))}"


def seguiti(u):
    """Enti seguiti: quelli scelti con 'Segui' + i 15 principali della mappa (tolti quelli smessi)."""
    cf = list(dict.fromkeys(u.get("enti") or []))
    if u["regione"].lower() not in ("tutta italia", ""):
        cats = [c for c in u["soa"] if c != "ALTRA"][:4] or ["OG 1", "OG 3"]
        cf += [e["cf"] for e in enti_bersaglio(u["regione"], cats, 15)]
    no = set(u.get("no_enti") or [])
    return [x for x in dict.fromkeys(cf) if x not in no]


def movimenti_enti(avvisi, u):
    """Cosa hanno fatto ieri gli enti seguiti: affidamenti, inviti, bandi, elenchi, preinformazioni, esiti (solo lavori)."""
    R, E = _indici()
    mio = set(seguiti(u))
    if not mio:
        return []
    out = []
    for a in avvisi:
        if a.get("tipo") != "avviso":
            continue
        e = E.get(_nome(a.get("ente")))
        if not e or e["cf"] not in mio or a["tipologia"] in ("MODIFICHE_CONTRATTUALI", "AFFIDAMENTI_IN_HOUSE", "SISTEMI_DI_QUALIFICAZIONE"):
            continue
        for it in a.get("items") or [{}]:
            if (it.get("natura") or "").lower() != "lavori" and a["tipologia"] not in ("ELENCHI_OPERATORI_ECONOMICI",):
                continue
            out.append((a, it, e["cf"]))
            break
    ordine = {"ELENCHI_OPERATORI_ECONOMICI": 0, "INDAGINI_DI_MERCATO_SOTTO_SOGLIA": 1, "AVVISI_DI_PRE-INFORMAZIONE_INDITTIVI": 2,
              "AVVISI_DI_PRE-INFORMAZIONE_INFORMATIVI": 2, "BANDI": 3, "AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA": 4, "RISULTATI": 5}
    return sorted(out, key=lambda x: (ordine.get(x[0]["tipologia"], 9), -(x[1].get("valore") or 0)))


ETICHETTE = {
    "ELENCHI_OPERATORI_ECONOMICI": ("Elenco imprese aperto", "#1f9d55", "#e7f6ee"),
    "INDAGINI_DI_MERCATO_SOTTO_SOGLIA": ("Cerca imprese da invitare", BLU, "#e8f1ff"),
    "AVVISI_DI_PRE-INFORMAZIONE_INDITTIVI": ("Gara in arrivo", "#7c3aed", "#f1eafe"),
    "AVVISI_DI_PRE-INFORMAZIONE_INFORMATIVI": ("Gara in arrivo", "#7c3aed", "#f1eafe"),
    "BANDI": ("Nuova gara", INK, "#f0f0f3"),
    "AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA": ("Affidato senza gara", "#c2410c", "#fdeee6"),
    "RISULTATI": ("Esito", INK2, "#f0f0f3"),
}


def link_segui(a):
    """'+ Segui' accanto all'ente nell'email, se l'iscritto non lo segue già."""
    R, E = _indici()
    e = E.get(_nome(a.get("ente")))
    if not e or e["cf"] in (PER_ISCRITTO_EXTRA.get("seguiti") or set()):
        return ""
    return f' · <a href="{html.escape(url_segui(e["cf"], a.get("ente")))}" style="color:{BLU};text-decoration:none;font-weight:600">+ Segui</a>'


def sezione_miei_enti(mov):
    if not mov:
        return ""
    righe = ""
    for a, it, cf in mov[:10]:
        et, fg, bg = ETICHETTE.get(a["tipologia"], ("Avviso", INK2, "#f0f0f3"))
        t = html.escape(pulito(a.get("titolo") or it.get("descr") or ""))
        imp = ", ".join(imprese(it))
        nota = ""
        if a["tipologia"] == "AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA" and imp:
            nota = (f'<div style="font-size:12px;color:{INK2};margin-top:4px">Affidato a <b>{html.escape(imp)}</b>. '
                    f'Per la rotazione, il prossimo affidamento simile dovrà andare a un\'altra impresa: fatti trovare pronto.</div>')
        elif a["tipologia"] == "RISULTATI" and imp:
            rb = ribasso(it)
            nota = f'<div style="font-size:12px;color:{INK2};margin-top:4px">Vinto da <b>{html.escape(imp)}</b>{(" con il " + virgola(rb) + "% di ribasso") if rb is not None else ""}.</div>'
        link = html.escape(url_scheda(it) if a["tipologia"] in ("BANDI", "INDAGINI_DI_MERCATO_SOTTO_SOGLIA") and it.get("cig") else (a.get("link") or SITE))
        righe += f"""<tr><td style="padding:12px 0;border-top:1px solid #f0f0f3">
<div>{pill(et, fg, bg)} <span style="font-size:12px;color:{INK3}">{html.escape(a.get('ente') or '')}</span></div>
<div style="font-size:14px;color:{INK};margin-top:6px;line-height:1.35"><a href="{link}" style="color:{INK};text-decoration:none">{t}</a>
{(' · <b>' + euro(it.get('valore')) + '</b>') if it.get('valore') else ''}</div>{nota}</td></tr>"""
    return titolo_sezione("I tuoi enti", f"Cosa hanno fatto ieri i tuoi enti", "Gli enti che segui: quelli della tua mappa e quelli che hai scelto con «Segui».") + f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:2px solid {BLU}"><tr><td style="padding:4px 22px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe}</table></td></tr></table>"""


def aggiorna_seguiti(key):
    """Legge da Brevo i clic su 'Segui' / 'Smetti' nelle email e aggiorna gli attributi ENTI / ENTI_NO dei contatti."""
    from urllib.parse import urlparse, parse_qs
    for nome in ("ENTI", "ENTI_NO"):
        try:
            http_json(f"{BREVO}/contacts/attributes/normal/{nome}", data={"type": "text"}, headers={"api-key": key}, method="POST")
        except Exception:
            pass
    try:
        ev = http_json(f"{BREVO}/smtp/statistics/events?event=clicks&days=3&limit=2500&sort=asc", headers={"api-key": key}).get("events") or []
    except Exception as e:
        print("Clic Brevo non leggibili:", e)
        return 0
    cambi = {}
    for x in ev:
        link = x.get("link") or ""
        if "segui.html" not in link:
            continue
        q = parse_qs(urlparse(link).query)
        em = x.get("email")
        if q.get("cf"):
            cambi.setdefault(em, []).append(("+", q["cf"][0]))
        elif q.get("off"):
            cambi.setdefault(em, []).append(("-", q["off"][0]))
    for em, ops in cambi.items():
        try:
            c = http_json(f"{BREVO}/contacts/{urllib.parse.quote(em)}", headers={"api-key": key})
            at = c.get("attributes") or {}
            si = [x for x in (at.get("ENTI") or "").split(",") if x]
            no = [x for x in (at.get("ENTI_NO") or "").split(",") if x]
            for op, cf in ops:
                if op == "+":
                    si = list(dict.fromkeys(si + [cf])); no = [x for x in no if x != cf]
                else:
                    no = list(dict.fromkeys(no + [cf])); si = [x for x in si if x != cf]
            http_json(f"{BREVO}/contacts/{urllib.parse.quote(em)}", data={"attributes": {"ENTI": ",".join(si), "ENTI_NO": ",".join(no)}},
                      headers={"api-key": key}, method="PUT")
        except Exception as e:
            print("  aggiornamento enti non riuscito per", em, e)
    return len(cambi)


# ---------------------------------------------------------------- quanto ti resta (stima del margine)
SG, UTILE = 0.15, 0.10           # spese generali e utile d'impresa compresi nei prezzi del prezzario (all. I.7: 13-17% e 10%)
RICARICO = (1 + SG) * (1 + UTILE)  # 1,265: prezzo di prezzario = costo vivo x 1,265


def margine(rib, diff_prezzi=0.0):
    """Margine stimato sui costi vivi con un ribasso dato. diff_prezzi = quanto i prezzi del progetto sono sopra/sotto il prezzario in vigore (%)."""
    return ((1 - rib / 100) * (1 + diff_prezzi / 100) * RICARICO - 1) * 100


def ribasso_pareggio(diff_prezzi=0.0):
    return (1 - 1 / (RICARICO * (1 + diff_prezzi / 100))) * 100


def resta(st, ac):
    """Dati per il riquadro 'Quanto ti resta'."""
    if not st:
        return None
    diff = (ac or {}).get("confronto", {}) or {}
    d = diff.get("diff", 0.0) if diff else 0.0
    return {"med": st["med"], "m_med": margine(st["med"], d), "m_p25": margine(st["p25"], d), "m_p75": margine(st["p75"], d),
            "pareggio": ribasso_pareggio(d), "diff": d, "verificato": bool(diff), "dove": st["livello"]}


def frase_resta(r):
    m = r["m_med"]
    if m < 0:
        giudizio, col = "con il ribasso che vince di solito si lavora in perdita", "#c2410c"
    elif m < 4:
        giudizio, col = "gara molto tirata", "#c2410c"
    elif m < 9:
        giudizio, col = "margine stretto", "#b45309"
    else:
        giudizio, col = "margine buono", "#1f9d55"
    return giudizio, col


def pag_resta(st, ac):
    r = resta(st, ac)
    if not r:
        return ""
    giud, col = frase_resta(r)
    righe = "".join(f'<tr><td>{lab}</td><td style="text-align:right">{virgola(rb)}%</td><td style="text-align:right;color:{"#c2410c" if m < 0 else "#1d1d1f"}"><b>{virgola(round(m, 1))}%</b></td></tr>'
                    for lab, rb, m in [("Ribasso basso (un quarto delle gare vinte sotto)", st["p25"], r["m_p25"]),
                                       ("Ribasso che vince di solito", st["med"], r["m_med"]),
                                       ("Ribasso alto (un quarto delle gare vinte sopra)", st["p75"], r["m_p75"])])
    nota = (f"I prezzi del progetto sono stati verificati voce per voce sul prezzario in vigore ({'in linea' if abs(r['diff']) < 1 else virgola(r['diff']) + '%'})."
            if r["verificato"] else "Calcolo fatto supponendo che i prezzi del progetto siano quelli del prezzario regionale.")
    return f"""<h2>Quanto ti resta</h2><p class="uff">Con il ribasso che vince di solito: <b style="color:{col}">{giud}</b>. Oltre il <b>{virgola(round(r['pareggio'], 1))}%</b> di ribasso si lavora in perdita.</p>
<table class="u"><tr><th>Scenario</th><th style="text-align:right">Ribasso</th><th style="text-align:right">Margine stimato sui costi</th></tr>{righe}</table>
<p class="f" style="text-align:left;margin-top:8px">I prezzi del prezzario comprendono circa il 15% di spese generali e il 10% di utile d'impresa (allegato I.7 del codice): il margine è calcolato sui costi vivi. {nota} I costi della manodopera e della sicurezza non soggetti a ribasso migliorano il risultato. Stima indicativa: il costo reale dipende dalla tua organizzazione.</p>"""


def blocco_resta(r):
    if not r:
        return ""
    giud, col = frase_resta(r)
    nota = ("prezzi del progetto verificati sul prezzario in vigore" if r["verificato"] else "se i prezzi sono quelli del prezzario regionale")
    return f"""<div style="margin-top:10px;background:#fbfbfd;border:1px solid #ececf0;border-radius:14px;padding:12px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:12px;color:{INK2}">Quanto ti resta · stima</td>
<td align="right" style="font-size:15px;font-weight:700;color:{col}">{virgola(round(r['m_med'], 1))}%</td></tr></table>
<div style="font-size:12px;color:{INK};margin-top:4px">Con il ribasso che vince di solito ({virgola(r['med'])}%): <b style="color:{col}">{giud}</b>. Oltre il {virgola(round(r['pareggio'], 1))}% di ribasso si lavora in perdita.</div>
<div style="font-size:11px;color:{INK3};margin-top:4px">Margine sui costi vivi, {nota}: i prezzi comprendono circa 15% di spese generali e 10% di utile. Stima indicativa, non un consiglio d'offerta.</div></div>"""


def virgola(x):
    return str(x).replace(".", ",")


def blocco_storico(st):
    """Riquadro nell'email: quanto ribassa chi vince da questo ente."""
    if not st:
        return ""
    dove = {"ente": "questo ente", "italia": "in Italia"}.get(st["livello"], st["dove"])
    w1, w2 = max(2, min(98, round(st["p25"] / 40 * 100))), max(4, min(100, round(st["p75"] / 40 * 100)))
    off = f" · in media {round(st['off'])} offerte" if st.get("off") else ""
    return f"""<div style="margin-top:14px;background:#f5f5f7;border-radius:14px;padding:12px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:12px;color:{INK2}">Ribasso che vince in gare simili</td>
<td align="right" style="font-size:15px;font-weight:700;color:{INK}">{virgola(st['med'])}%</td></tr></table>
<div style="position:relative;height:8px;background:#e3e3e8;border-radius:99px;margin:8px 0 6px">
<div style="margin-left:{w1}%;width:{max(3, w2 - w1)}%;height:8px;background:{BLU};border-radius:99px"></div></div>
<div style="font-size:11px;color:{INK3}">{html.escape(st.get('descr', ''))}, 2023-2025 · metà vinte tra {virgola(st['p25'])}% e {virgola(st['p75'])}%{off}</div></div>"""


def barra_ribasso(r):
    w = max(8, min(100, round(r / 30 * 100)))
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px"><tr>
<td style="font-size:12px;color:{INK2};padding-bottom:6px">Ribasso che vince di solito</td>
<td align="right" style="font-size:13px;font-weight:700;color:{INK};padding-bottom:6px">{str(r).replace('.', ',')}%</td></tr>
<tr><td colspan="2"><div style="height:8px;background:#ececf0;border-radius:99px"><div style="height:8px;width:{w}%;background:{BLU};border-radius:99px"></div></div></td></tr></table>"""


def scheda(a, it, soa, tipo):
    cats = " · ".join(it["cat"]) or "categoria n.d."
    if tipo == "indagine":
        badge = pill("✉︎ Candidati per essere invitato", BLU, "#e8f1ff")
        accento = BLU
    else:
        manca = [c for c in it["cat"] if c not in soa] if soa and "ALTRA" not in soa else []
        cl = (PER_ISCRITTO_EXTRA.get("classi") or {}).get(prevalente(it) or "")
        if not manca and cl and (it.get("valore") or 0) > CLASSI.get(cl, 10**12) * 1.2:
            badge, accento = pill(f"Supera la tua classifica {cl}: serve un raggruppamento", "#c2410c", "#fdeee6"), "#ff9f0a"
        elif not manca:
            badge, accento = pill("✓ Puoi partecipare", "#1f9d55", "#e7f6ee"), "#34c759"
        else:
            badge = pill(f"Ti serve un partner {', '.join(manca[:3])}{' +' if len(manca) > 3 else ''}", "#c2410c", "#fdeee6")
            accento = "#ff9f0a"
            nomi = []
            for c in manca[:2]:
                ps, _ = partner_per(a, c, 3)
                if ps:
                    nomi.append(f"<b>{c.replace(' ', '')}</b>: " + ", ".join(html.escape(titolo_ente(p['nome'])) for p in ps))
            if nomi:
                badge += (f'<div style="font-size:12px;color:{INK2};margin-top:8px;line-height:1.5">🤝 Partner possibili in zona · '
                          + " · ".join(nomi) + f' <a href="{html.escape(url_scheda(it))}#partner" style="color:{BLU};text-decoration:none;font-weight:600">tutti ›</a></div>')
    rib = ""
    ac = analisi_computo(it)
    if ac:
        pz = ac["prezzari"][0] if ac["prezzari"] else None
        bits = [f"{ac['top3_quota']}% dell'importo in 3 lavorazioni"]
        if ac["np_quota"] >= 15:
            bits.append(f"{ac['np_quota']}% in nuovi prezzi")
        if pz and pz["anno"] < 2026:
            bits.append(f"prezzario {pz['regione']} {pz['anno']}: prezzi vecchi")
        if ac.get("confronto") and abs(ac["confronto"]["diff"]) >= 2:
            d_ = ac["confronto"]["diff"]
            bits.append(f"prezzi {virgola(abs(d_))}% {'sotto' if d_ < 0 else 'sopra'} il prezzario 2026")
        rib_comp = (f'<div style="font-size:12px;color:{INK2};margin-top:10px">📊 <b>Computo</b> · ' + " · ".join(html.escape(b) for b in bits) +
                    f' <a href="{html.escape(url_scheda(it))}#computo" style="color:{BLU};text-decoration:none;font-weight:600">analisi ›</a></div>')
    else:
        rib_comp = ""
    if tipo == "bando":
        st = storico(a, it)
        rib = blocco_storico(st) if st else barra_ribasso(next((RIBASSO[c] for c in it["cat"] if c in RIBASSO), RIBASSO_TUTTI))
        rib += blocco_resta(resta(st, ac))
    res = RESOCONTI.get(it.get("cig") or "")
    ufficiale = pulito(a["titolo"] or it["descr"] or "Lavori")
    if len(ufficiale) < 20 and (it.get("descr") or "").strip():   # titoli tipo "Lotto 1": meglio la descrizione
        ufficiale = pulito(it["descr"])
    descr = pulito(it.get("descr") or "")
    if descr and descr.lower() not in ufficiale.lower() and ufficiale.lower() not in descr.lower():
        ufficiale = f"{ufficiale} — {descr}"
    breve_tit = (res or {}).get("titolo")
    t = breve_tit or ufficiale
    titolo = html.escape(t if len(t) <= 120 else t[:115].rsplit(" ", 1)[0] + "…")
    oggetto = ""
    cosa = ""
    if res and res.get("lavori"):
        cosa = (f'<div style="font-size:14px;color:{INK};line-height:1.5;margin:0 0 10px">'
                f'<b style="color:{BLU}">Cosa si fa ·</b> {html.escape(res["lavori"])}</div>')
    oggetto = (f'<div style="margin:0 0 12px"><a href="{html.escape(url_scheda(it))}" style="font-size:14px;font-weight:600;color:{BLU};text-decoration:none">'
               f'▸ Leggi la descrizione completa</a></div>')
    link = html.escape(a.get("link") or SITE)
    breve = ""
    if res and res.get("punti"):
        righe = "".join(
            f'<tr><td valign="top" style="font-size:13px;color:{INK2};padding:5px 10px 5px 0;white-space:nowrap">{html.escape(p.get("t", ""))}</td>'
            f'<td style="font-size:13px;color:{INK};padding:5px 0">{html.escape(p.get("v", ""))}'
            f'{(" <span style=\"color:" + INK3 + ";font-size:11px\">· " + html.escape(p["fonte"]) + "</span>") if p.get("fonte") else ""}</td></tr>'
            for p in res["punti"][:9])
        att = "".join(f'<div style="font-size:13px;color:#c2410c;margin-top:6px">⚠︎ {html.escape(x)}</div>' for x in (res.get("attenzione") or [])[:3])
        breve = (f'<div style="margin-top:16px;background:#f5f5f7;border-radius:16px;padding:14px 16px">'
                 f'<div style="font-size:12px;font-weight:700;color:{BLU};margin-bottom:6px">IN BREVE · letto dai documenti di gara</div>'
                 f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{righe}</table>{att}</div>')
    com = it.get("istat") and str(it["istat"]).title()
    if com and com.lower() in (a.get("ente") or "").lower():
        com = None
    luogo = " · ".join(x for x in [com, regione(it)] if x)
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px;background:#ffffff;border-radius:22px;border:1px solid #ececf0">
<tr><td style="padding:20px 22px;border-left:4px solid {accento};border-radius:22px">
<div style="font-size:12px;color:{INK3};margin-bottom:6px">{html.escape((a['ente'] or '')[:70])}{(' · ' + html.escape(luogo)) if luogo else ''}{link_segui(a)}</div>
<div style="font-size:17px;font-weight:650;line-height:1.3;color:{INK};letter-spacing:-.01em;margin-bottom:12px">{titolo}</div>
{oggetto}{cosa}<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:26px;font-weight:700;letter-spacing:-.03em;color:{INK};padding-right:14px">{euro(it.get('valore'))}</td>
<td style="font-size:12px;color:{INK2}">{html.escape(cats)}</td></tr></table>
<div style="margin-top:12px">{badge} &nbsp;{scad_pill(it.get('scadenza') or a.get('scadenza'))}{(' &nbsp;' + pill('Regione vicina · ' + html.escape(regione(it) or ''), INK2, '#f0f0f3')) if it.get('_zona') == 'vicina' else ''}</div>
{rib}
{rib_comp}
{breve}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:16px"><tr>
<td style="background:{BLU};border-radius:999px"><a href="{link}" style="display:inline-block;padding:10px 18px;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none">Apri i documenti</a></td>
<td style="padding-left:12px;font-size:11px;color:{INK3}">CIG {html.escape(it.get('cig') or '')}</td></tr></table>
</td></tr></table>"""


def analisi_computo(it, giorno=None):
    """Analisi del computo metrico, se tra i documenti scaricati c'è (testi/AAAA/MM/GG/CIG/computo.json.gz)."""
    import glob
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from computo import analisi
    cig = it.get("cig")
    if not cig:
        return None
    for f in sorted(glob.glob(f"testi/*/*/*/{cig}/computo.json.gz"), reverse=True)[:1]:
        try:
            docs = json.load(gzip.open(f, "rt"))
        except Exception:
            return None
        migliore = None
        for d in docs:
            if d.get("tipo") == "computo" or re.search(r"comput|metrico", d.get("nome", ""), re.I):
                a = analisi(d.get("testo") or "")
                if a and (not migliore or a["voci"] > migliore["voci"]):
                    migliore = a
        return migliore
    return None


def url_scheda(it):
    return f"{SITE}g/{it.get('cig')}.html"


def pagina_gara(a, it, tipo):
    """Scheda web completa della gara (si apre da 'Leggi tutto' nell'email)."""
    res = RESOCONTI.get(it.get("cig") or "") or {}
    ufficiale = pulito(a.get("titolo") or it.get("descr") or "Lavori")
    descr = pulito(it.get("descr") or "")
    titolo = res.get("titolo") or ufficiale
    luogo = " · ".join(x for x in [it.get("istat") and str(it["istat"]).title(), regione(it)] if x)
    d, gg = giorni_a(it.get("scadenza") or a.get("scadenza") or "")
    scad = f"{d:%d/%m/%Y %H:%M}" + (f" · tra {gg} giorni" if gg is not None and gg >= 0 else "") if d else "Non indicata"
    e = html.escape
    punti = "".join(f'<tr><th>{e(p.get("t",""))}</th><td>{e(p.get("v",""))}'
                    f'{("<small>" + e(p["fonte"]) + "</small>") if p.get("fonte") else ""}</td></tr>'
                    for p in res.get("punti") or [])
    att = "".join(f"<li>{e(x)}</li>" for x in res.get("attenzione") or [])
    blocco_descr = f'<h2>Descrizione</h2><p>{e(descr)}</p>' if descr and descr.lower() not in ufficiale.lower() else ""
    blocco_partner = ""
    sezioni = []
    for c in [x for x in (it.get("cat") or []) if x != prevalente(it)][:4]:
        ps, prov = partner_per(a, c, 8)
        if ps:
            r = "".join(f'<tr><td>{e(titolo_ente(pubblico(p["nome"])))}</td><td>{e(p["cl"] or "")}</td>'
                        f'<td style="text-align:right">{p["vc"]}</td><td style="text-align:right">{p["v"]}</td></tr>' for p in ps)
            sezioni.append(f'<h2>{e(c.replace(" ", ""))}{(" · provincia di " + e(titolo_ente(prov))) if prov else ""}</h2>'
                           f'<table class="u"><tr><th>Impresa</th><th>Classifica</th><th>Gare {e(c.replace(" ", ""))} vinte</th><th>Gare vinte in tutto</th></tr>{r}</table>')
    if sezioni:
        blocco_partner = ('<div class="card" id="partner"><h2 style="margin-top:0;color:#007aff">Trova partner per le altre categorie</h2>'
                          '<p class="uff">Imprese con attestazione SOA in corso di validità nelle categorie richieste dalla gara oltre alla prevalente, '
                          'vicino all\'ente. Utili per un raggruppamento (RTI) o per l\'avvalimento.</p>' + "".join(sezioni) +
                          '<p class="f" style="text-align:left;margin-top:12px">Fonte: attestazioni SOA e aggiudicazioni 2023-2025 (ANAC, CC BY-SA 4.0).</p></div>')
    ac = analisi_computo(it)
    blocco_comp = ""
    if ac:
        pz = ac["prezzari"][0] if ac["prezzari"] else None
        if pz and pz["anno"] >= 2026:
            nota_pz = f'Prezzi dal prezzario <b>{e(pz["regione"])} {pz["anno"]}</b>, quello in vigore ({pz["quota"]}% dell\'importo).'
        elif pz:
            nota_pz = (f'<span style="color:#c2410c">Prezzi dal prezzario <b>{e(pz["regione"])} {pz["anno"]}</b> ({pz["quota"]}% dell\'importo): '
                       f'sono di {2026 - pz["anno"]} anni fa, i costi reali oggi possono essere più alti. Margine da verificare bene.</span>')
        else:
            nota_pz = "Prezzario di riferimento non riconosciuto dai codici delle voci."
        cf_ = ac.get("confronto")
        if cf_:
            verso = "sotto" if cf_["diff"] < 0 else "sopra"
            colore = "#c2410c" if cf_["diff"] <= -3 else ("#1f9d55" if cf_["diff"] >= 3 else "#1d1d1f")
            giud = (f"in linea con il prezzario in vigore" if abs(cf_["diff"]) < 1 else f"<b>{virgola(abs(cf_['diff']))}% {verso}</b> il prezzario in vigore")
            nota_pz += (f'<br><span style="color:{colore}">Confronto voce per voce: sulle {cf_["voci"]} voci confrontabili '
                        f'({euro(cf_["importo"])}) i prezzi del progetto sono {giud}.</span>') if pz else ""
        nota_np = ""
        if ac["np_quota"] >= 15:
            nota_np = (f'<p style="margin-top:8px"><b>{ac["np_quota"]}% dell\'importo è in nuovi prezzi</b> (voci fuori prezzario, prezzate dal progettista con '
                       f'un\'analisi): è lì che si gioca il margine. Controlla l\'elenco prezzi e le analisi dei nuovi prezzi.</p>')
        if ac.get("np_check"):
            r_np = "".join(f'<tr><td>{e(frase(x["descr"]))}<small>{e(x["cod"])}</small></td><td style="text-align:right">{euro(x["prezzo"])}/{e(x["um"])}</td>'
                           f'<td>{e(frase(x["simile"]))}<small>{e(x["simile_cod"])}</small></td><td style="text-align:right">{euro(x["simile_prezzo"])}</td>'
                           f'<td style="text-align:right;color:{"#c2410c" if x["rapporto"] < 1 else "#1f9d55"}"><b>{"−" if x["rapporto"] < 1 else "+"}{round(abs(1 - x["rapporto"]) * 100)}%</b></td></tr>'
                           for x in ac["np_check"])
            nota_np += ('<h2>Nuovi prezzi da controllare</h2><p class="uff">Voci fuori prezzario confrontate con la voce più simile del prezzario in vigore. '
                        'Un prezzo molto più basso può nascondere un costo non coperto; controlla l\'analisi del nuovo prezzo.</p>'
                        f'<div style="overflow-x:auto"><table class="u"><tr><th>Nuovo prezzo</th><th>Prezzo</th><th>Voce simile del prezzario</th><th>Prezzo</th><th>Differenza</th></tr>{r_np}</table></div>')
        righe = "".join(f'<tr><td>{e(frase(v["descr"]) or "—")}<small>{e(v["cod"])}</small></td><td style="text-align:right">{virgola(round(v["qta"], 2)) if v["qta"] else ""} {e(v["um"])}</td>'
                        f'<td style="text-align:right">{euro(v["prezzo"]) if v["prezzo"] else ""}</td><td style="text-align:right"><b>{euro(v["imp"])}</b></td>'
                        f'<td style="text-align:right">{virgola(v["quota"])}%</td></tr>' for v in ac["top"][:6])
        blocco_comp = f"""<div class="card" id="computo"><h2 style="margin-top:0;color:#007aff">Analisi del computo metrico</h2>
<div class="imp">{euro(ac['totale'])}</div><p class="uff">{ac['voci']} voci lette dal computo metrico estimativo · le prime 3 lavorazioni valgono il <b>{ac['top3_quota']}%</b> dell'importo.</p>
<p style="margin-top:8px">{nota_pz}</p>{nota_np}
<h2>Dove sono i soldi</h2><div style="overflow-x:auto"><table class="u"><tr><th>Lavorazione</th><th>Quantità</th><th>Prezzo</th><th>Importo</th><th>Peso</th></tr>{righe}</table></div>
<p class="f" style="text-align:left;margin-top:12px">Letto in automatico dal computo metrico pubblicato tra i documenti di gara: controlla sempre il documento originale.</p></div>"""
    st = storico(a, it)
    blocco_st = ""
    if st:
        dove = {"ente": e(a.get("ente") or "questo ente"), "italia": "in Italia"}.get(st["livello"], e(st["dove"] or ""))
        righe = "".join(f'<tr><td>{e(x["d"])}</td><td>{e(frase(x["g"]))}</td><td style="text-align:right">{euro(x["i"]) if x["i"] else "—"}</td>'
                        f'<td style="text-align:right"><b>{virgola(x["r"])}%</b></td><td style="text-align:right">{x["o"] or "—"}</td><td>{e(pubblico(x["v"]))}</td></tr>'
                        for x in (st.get("ultime") or (st.get("ente_poche") or {}).get("ultime") or []))
        tab = (f'<h2>Le ultime gare {st["cat"]} di {e(a.get("ente") or "questo ente")}</h2><div style="overflow-x:auto"><table class="u"><tr><th>Mese</th><th>Oggetto</th><th>Base</th><th>Ribasso</th><th>Offerte</th><th>Vincitore</th></tr>{righe}</table></div>') if righe else ""
        blocco_st = f"""<div class="card"><h2 style="margin-top:0;color:#007aff">Quanto si ribassa per vincere</h2>
<div class="imp">{virgola(st['med'])}%</div><p class="uff">Ribasso mediano di {e(st.get('descr', ''))} (2023-2025). Metà delle gare tra <b>{virgola(st['p25'])}%</b> e <b>{virgola(st['p75'])}%</b> · {st['n']} gare{(' · in media ' + str(round(st['off'])) + ' offerte') if st.get('off') else ''}.</p>
{pag_resta(st, ac)}
{tab}<p class="f" style="text-align:left;margin-top:12px">Dati di mercato dalla Banca dati nazionale dei contratti pubblici (ANAC, CC BY-SA 4.0). Non è un consiglio d'offerta: ogni gara ha il suo progetto e i suoi prezzi.</p></div>"""
    return f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titolo[:90])} · GaraPronta</title><meta name="robots" content="noindex">
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&display=swap" rel="stylesheet">
<style>
body{{margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1d1d1f;background:#f5f5f7;line-height:1.55;-webkit-font-smoothing:antialiased}}
.w{{max-width:760px;margin:0 auto;padding:0 18px 50px}} header{{padding:22px 0}} header a{{font-weight:650;color:#1d1d1f;text-decoration:none}}
.card{{background:#fff;border:1px solid #e5e5ea;border-radius:26px;padding:28px 26px;margin-bottom:16px}}
.ente{{font-size:13px;color:#86868b}} h1{{font-size:28px;letter-spacing:-.03em;line-height:1.15;margin:6px 0 14px}}
.imp{{font-size:34px;font-weight:700;letter-spacing:-.03em}} .pill{{display:inline-block;background:#f0f0f3;border-radius:99px;padding:6px 12px;font-size:13px;font-weight:600;margin:10px 6px 0 0}}
.pill.b{{background:#e8f1ff;color:#007aff}} h2{{font-size:17px;margin:22px 0 6px}} p{{margin:0;font-size:15px}}
.uff{{color:#6e6e73;font-size:14px}} table{{width:100%;border-collapse:collapse}} th{{text-align:left;vertical-align:top;font-size:13px;color:#6e6e73;font-weight:500;padding:9px 12px 9px 0;width:120px;border-top:1px solid #f0f0f3}}
td{{font-size:14px;padding:9px 0;border-top:1px solid #f0f0f3}} small{{display:block;color:#86868b;font-size:11px;margin-top:2px}}
.att li{{color:#c2410c;font-size:14px;margin:4px 0}} .btn{{display:inline-block;background:#007aff;color:#fff;text-decoration:none;font-weight:600;border-radius:99px;padding:12px 22px;margin-top:8px}}
.f{{font-size:12px;color:#86868b;text-align:center}}
table.u th{{width:auto;font-size:11px;padding:6px 8px 6px 0}} table.u td{{font-size:12px;padding:7px 8px 7px 0;vertical-align:top}}
</style></head><body><div class="w">
<header><a href="{SITE}">● GaraPronta</a></header>
<div class="card">
<div class="ente">{e(a.get("ente") or "")}{(" · " + e(luogo)) if luogo else ""}</div>
<h1>{e(titolo)}</h1>
<div class="imp">{euro(it.get("valore"))}</div>
<span class="pill b">{"Indagine di mercato · candidati per essere invitato" if tipo == "indagine" else "Gara aperta"}</span><span class="pill">{e(" · ".join(it.get("cat") or []) or "categoria n.d.")}</span><span class="pill">Scadenza {e(scad)}</span>
{f'<h2>Cosa si fa</h2><p>{e(res["lavori"])}</p>' if res.get("lavori") else ""}
<h2>Oggetto ufficiale</h2><p class="uff">{e(ufficiale)}</p>
{blocco_descr}
<div style="margin-top:22px"><a class="btn" href="{e(a.get("link") or SITE)}">Apri i documenti di gara</a></div>
</div>
{blocco_st}
{blocco_comp}
{blocco_partner}
{f'<div class="card"><h2 style="margin-top:0;color:#007aff">In breve · letto dai documenti di gara</h2><table>{punti}</table>' + (f'<ul class="att">{att}</ul>' if att else "") + "</div>" if punti else ""}
<div class="card"><table>
<tr><th>Ente</th><td>{e(a.get("ente") or "")}</td></tr>
<tr><th>CIG</th><td>{e(it.get("cig") or "")}</td></tr>
<tr><th>Procedura</th><td>{e(a.get("procedura") or ("Indagine di mercato" if tipo == "indagine" else "Bando"))}</td></tr>
<tr><th>Pubblicata</th><td>{e((a.get("pubblicato") or "")[:10])}</td></tr></table></div>
<p class="f">Fonte: Piattaforma di pubblicità legale ANAC (CC BY 4.0). Il riassunto è letto in automatico dai documenti: controlla sempre i documenti ufficiali prima di partecipare. · <a href="{SITE}privacy.html" style="color:#86868b">Privacy</a></p>
</div></body></html>"""


def scrivi_schede(avvisi):
    os.makedirs("g", exist_ok=True)
    n = 0
    for a in avvisi:
        if a["tipo"] != "avviso" or a["tipologia"] not in ("BANDI", "INDAGINI_DI_MERCATO_SOTTO_SOGLIA"):
            continue
        for it in a["items"]:
            if (it.get("natura") or "").lower() == "lavori" and it.get("cig"):
                tipo = "indagine" if a["tipologia"].startswith("INDAGINI") else "bando"
                with open(f"g/{it['cig']}.html", "w", encoding="utf-8") as f:
                    f.write(pagina_gara(a, it, tipo))
                n += 1
    return n


def titolo_sezione(eyebrow, titolo, sotto):
    return f"""<div style="margin:34px 0 14px">
<div style="font-size:13px;font-weight:600;color:{BLU};margin-bottom:4px">{eyebrow}</div>
<div style="font-size:24px;font-weight:700;letter-spacing:-.03em;color:{INK}">{titolo}</div>
<div style="font-size:14px;color:{INK2};margin-top:4px">{sotto}</div></div>"""


def tile(numero, etichetta, colore=INK):
    return f"""<td width="33%" valign="top" style="padding:4px"><div style="background:rgba(255,255,255,.75);border-radius:18px;padding:16px 14px;border:1px solid rgba(255,255,255,.9)">
<div style="font-size:30px;font-weight:700;letter-spacing:-.04em;color:{colore};line-height:1">{numero}</div>
<div style="font-size:12px;color:{INK2};margin-top:6px;line-height:1.3">{etichetta}</div></div></td>"""


def riepilogo_diretti(diretti, u):
    if not diretti:
        return ""
    tot = sum(it.get("valore") or 0 for _, it in diretti)
    enti = Counter(a["ente"] for a, _ in diretti if a["ente"]).most_common(4)
    mx = enti[0][1] if enti else 1
    zona = "in Italia" if u["regione"].lower() in ("tutta italia", "") else f"in {u['regione']}"
    righe = "".join(f"""<tr><td style="font-size:13px;color:{INK};padding:7px 0;width:55%">{html.escape(e[:45])}</td>
<td style="padding:7px 10px"><div style="height:8px;background:#ececf0;border-radius:99px"><div style="height:8px;width:{max(10, round(n / mx * 100))}%;background:{BLU};border-radius:99px"></div></div></td>
<td align="right" style="font-size:13px;font-weight:700;color:{INK}">{n}</td></tr>""" for e, n in enti)
    return titolo_sezione("Lavori senza gara", f"{len(diretti)} affidamenti diretti {zona}",
                          f"Valore totale {euro(tot)}. Gli enti più attivi ieri:") + f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:16px 22px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe}</table>
<div style="font-size:12px;color:{INK2};margin-top:10px;line-height:1.45">Questi enti scelgono le imprese dai loro elenchi e dalle indagini di mercato. Iscriversi agli elenchi è il primo passo per essere chiamati.</div>
</td></tr></table>"""


def riga_vincitore(a, it, con_ribasso):
    t = html.escape(pulito(a.get("titolo") or it.get("descr") or "Lavori"))
    imp = html.escape(", ".join(imprese(it))[:90])
    rb = ribasso(it) if con_ribasso else None
    destra = (f'<div style="font-size:15px;font-weight:700;color:{INK}">{euro(it.get("vincente") or it.get("valore"))}</div>'
              + (f'<div style="font-size:12px;font-weight:600;color:#1f9d55">−{str(rb).replace(".", ",")}%</div>' if rb is not None else ""))
    return f"""<tr><td style="padding:12px 0;border-top:1px solid #f0f0f3" valign="top">
<div style="font-size:12px;color:{INK3}">{html.escape((a.get('ente') or '')[:60])}{(' · ' + " ".join(it['cat'][:2])) if it.get('cat') else ''}</div>
<div style="font-size:14px;color:{INK};margin:2px 0 4px;line-height:1.3">{t}</div>
<div style="font-size:13px;font-weight:650;color:{BLU}">🏆 {imp}</div></td>
<td align="right" valign="top" style="padding:12px 0 12px 12px;border-top:1px solid #f0f0f3;white-space:nowrap">{destra}</td></tr>"""


def sezione_vincitori(titolo_e, titolo, sotto, righe, con_ribasso, nota=""):
    if not righe:
        return ""
    corpo = "".join(riga_vincitore(a, it, con_ribasso) for a, it in righe)
    return titolo_sezione(titolo_e, titolo, sotto) + f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:6px 22px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{corpo}</table>
{f'<div style="font-size:12px;color:{INK2};margin-top:8px;line-height:1.45">{nota}</div>' if nota else ''}</td></tr></table>"""


def email_html(u, bandi, indagini, elenchi, diretti, giorno):
    soa = set(u["soa"])
    n = len(bandi) + len(indagini)
    profilo = f'{" · ".join(u["soa"]) or "Tutte le categorie"} · {u["regione"]}'
    gg = datetime.strptime(giorno, "%d/%m/%Y")
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    data_txt = f"{gg.day} {mesi[gg.month - 1]}"
    head = f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-radius:28px;background:#dbe9ff;background-image:linear-gradient(135deg,#cfe6ff 0%,#eef3ff 45%,#f3ecff 100%)">
<tr><td style="padding:26px 24px 20px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:16px;font-weight:650;color:{INK}"><span style="display:inline-block;width:20px;height:20px;border-radius:6px;background:{INK};vertical-align:-4px;margin-right:8px;text-align:center"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{BLU};margin-top:6.5px"></span></span>GaraPronta</td>
<td align="right" style="font-size:12px;color:{INK2}">{data_txt}</td></tr></table>
<div style="font-size:40px;font-weight:700;letter-spacing:-.045em;line-height:1.02;color:{INK};margin:26px 0 8px">{n} occasioni<br><span style="color:{INK3}">per te oggi.</span></div>
<div style="font-size:13px;color:{INK2};margin-bottom:18px">{html.escape(profilo)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
{tile(len(indagini), "inviti a cui candidarti", BLU)}{tile(len(bandi), "gare aperte per te")}{tile(len(diretti), "lavori affidati senza gara")}
</tr></table></td></tr></table>"""
    blocchi = [head, sezione_miei_enti(PER_ISCRITTO_EXTRA.get("mov") or [])]
    if indagini:
        blocchi.append(titolo_sezione("Fatti invitare", "Cercano imprese come la tua",
                                      "Candidati entro la scadenza per essere invitato alla gara.") +
                       "".join(scheda(a, it, soa, "indagine") for a, it in indagini[:8]))
    if bandi:
        blocchi.append(titolo_sezione("Gare aperte", "Le gare per le tue categorie",
                                      "Ordinate per importo. Il verde vuol dire che hai già tutto.") +
                       "".join(scheda(a, it, soa, "bando") for a, it in bandi[:10]))
    if elenchi:
        blocchi.append(titolo_sezione("Elenchi aperti", "Iscriviti e fatti chiamare", "Enti che stanno raccogliendo le imprese da invitare.") +
                       "".join(f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 12px;background:#fff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:18px 22px">
<div style="font-size:15px;font-weight:650;color:{INK}">{html.escape(a['ente'][:70])}</div>
<div style="font-size:13px;color:{INK2};margin:4px 0 12px">{html.escape(pulito(a['titolo'] or it['descr']))}</div>
<a href="{html.escape(a.get('link') or SITE)}" style="color:{BLU};font-size:14px;font-weight:600;text-decoration:none">Come iscriversi →</a></td></tr></table>""" for a, it in elenchi))
    cerc = PER_ISCRITTO_EXTRA.get("cercano") or []
    if cerc:
        righe_c = "".join(f"""<tr><td style="padding:12px 0;border-top:1px solid #f0f0f3">
<div style="font-size:12px;color:{INK3}">{html.escape(a.get('ente') or '')} · {html.escape(regione(it) or '')}</div>
<div style="font-size:14px;color:{INK};margin:3px 0"><a href="{html.escape(url_scheda(it))}" style="color:{INK};text-decoration:none">{html.escape(pulito(a.get('titolo') or it.get('descr') or ''))}</a></div>
<div style="font-size:12px;color:{INK2}">{euro(it.get('valore'))} · prevalente <b>{html.escape((prevalente(it) or '').replace(' ', ''))}</b> · serve anche <b style="color:{BLU}">{html.escape(', '.join(c.replace(' ', '') for c in it['cat'] if c in set(u['soa'])))}</b></div></td></tr>""" for a, it in cerc)
        blocchi.append(titolo_sezione("Cercano proprio te", "Gare dove serve la tua specializzazione",
                                      "La tua categoria è richiesta come secondaria: le imprese che partecipano devono avere un partner come te (raggruppamento o subappalto qualificato).") +
                       f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:4px 22px 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe_c}</table></td></tr></table>')
    esiti = PER_ISCRITTO_EXTRA.get("esiti") or []
    if esiti:
        rbs = [ribasso(it) for _, it in esiti if ribasso(it) is not None]
        med = sorted(rbs)[len(rbs) // 2] if rbs else None
        blocchi.append(sezione_vincitori(
            "Esiti di gara", "Chi ha vinto ieri",
            f"{len(esiti)} gare aggiudicate nelle tue categorie" + (f" · ribasso mediano {str(med).replace('.', ',')}%" if med is not None else ""),
            esiti[:8], True, "Importo di aggiudicazione e ribasso rispetto alla base d'asta, dai dati ANAC."))
    if datetime.now(timezone.utc).weekday() == 0 or os.environ.get("MAPPA") == "1":
        blocchi.append(sezione_enti(u))
    blocchi.append(riepilogo_diretti(diretti, u))
    top = PER_ISCRITTO_EXTRA.get("diretti_top") or []
    if top:
        blocchi.append(sezione_vincitori(
            "Affidamenti diretti", "A chi sono andati i lavori",
            "I più rilevanti per te, con l'impresa scelta dall'ente.", top[:8], False,
            "Sotto i 150.000 € l'ente sceglie l'impresa e deve ruotare gli inviti: chi è iscritto ai suoi elenchi ha più occasioni di essere chiamato."))
    if not (indagini or bandi or elenchi):
        blocchi.insert(1, f'<div style="background:#fff;border-radius:22px;border:1px solid #ececf0;padding:18px 22px;margin-top:20px;font-size:14px;color:{INK}">Ieri nessuna gara nuova per le tue categorie nella tua zona. Ti scriviamo appena esce.</div>')
    corpo = f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"></head>
<body style="margin:0;padding:0;background:#f5f5f7;font-family:{FONT};color:{INK};-webkit-font-smoothing:antialiased">
<div style="display:none;max-height:0;overflow:hidden">{len(indagini)} inviti, {len(bandi)} gare aperte e {len(diretti)} lavori diretti nella tua zona.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f7"><tr><td align="center" style="padding:20px 12px 40px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px"><tr><td>
{''.join(blocchi)}
<div style="text-align:center;margin:34px 0 0">
<table role="presentation" cellpadding="0" cellspacing="0" align="center"><tr><td style="background:{INK};border-radius:999px"><a href="{SITE}" style="display:inline-block;padding:12px 22px;color:#fff;font-size:14px;font-weight:600;text-decoration:none">Modifica categorie e zona</a></td></tr></table></div>
<div style="font-size:11px;color:{INK3};margin-top:26px;line-height:1.55;text-align:center">Fonte: Piattaforma di pubblicità legale ANAC (dati CC BY 4.0). Controlla sempre i requisiti sui documenti ufficiali.<br>
Ribassi: mediana delle gare vinte 2023-2025, dalla Banca dati nazionale dei contratti pubblici (ANAC, CC BY-SA 4.0). È un dato di mercato, non un consiglio d'offerta.<br>
Ricevi questa email perché ti sei iscritto a GaraPronta · <a href="mailto:garapronta@gmail.com?subject=Disiscrivimi" style="color:{INK3}">Disiscriviti</a> · <a href="{SITE}privacy.html" style="color:{INK3}">Privacy</a></div>
</td></tr></table></td></tr></table></body></html>"""
    return corpo, n


def invia(key, to, oggetto, corpo):
    return http_json(f"{BREVO}/smtp/email", headers={"api-key": key}, method="POST", data={
        "sender": SENDER, "to": [{"email": to}], "subject": oggetto, "htmlContent": corpo,
        "tags": ["garapronta-giornaliera"]})


# ---------------------------------------------------------------- main
def main():
    global RESOCONTI
    giorno = os.environ.get("DATA") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d/%m/%Y")
    modo = os.environ.get("MODE", "tutto")
    print(f"== Giorno {giorno} · modo {modo}")
    dd = datetime.strptime(giorno, "%d/%m/%Y")
    if modo in ("invio", "schede") and os.path.exists(f"data/{dd:%Y/%m/%d}.json.gz"):
        avvisi = json.load(gzip.open(f"data/{dd:%Y/%m/%d}.json.gz", "rt"))
        print(f"Letti {len(avvisi)} avvisi salvati")
    else:
        grezzi = scarica(giorno)
        avvisi = [estrai(a) for a in grezzi]
        path = salva(giorno, avvisi)
        print(f"Scaricati {len(grezzi)} avvisi, salvati in {path}")
    if modo == "dati":
        return
    if modo == "schede":
        dd2 = datetime.strptime(giorno, "%d/%m/%Y")
        rp = f"resoconti/{dd2:%Y/%m/%d}.json"
        RESOCONTI = json.load(open(rp)) if os.path.exists(rp) else {}
        print(f"Schede web scritte: {scrivi_schede(avvisi)}")
        key = os.environ.get("BREVO_API_KEY")
        if key:
            print(f"Mappe enti scritte: {scrivi_mappe(iscritti(key, os.environ.get('BREVO_LIST_ID', '5')))}")
        return
    rp = f"resoconti/{dd:%Y/%m/%d}.json"
    RESOCONTI = json.load(open(rp)) if os.path.exists(rp) else {}
    print(f"Resoconti disponibili: {len(RESOCONTI)}")
    print("Per tipologia:", dict(Counter(a["tipologia"] for a in avvisi if a["tipo"] == "avviso").most_common()))

    key = os.environ.get("BREVO_API_KEY")
    if not key:
        print("Nessuna BREVO_API_KEY: mi fermo dopo il salvataggio.")
        return
    print(f"Clic su Segui/Non seguire elaborati: {aggiorna_seguiti(key)}")
    utenti = iscritti(key, os.environ.get("BREVO_LIST_ID", "5"))
    live, dry = os.environ.get("LIVE") == "1", os.environ.get("DRY") == "1"
    print(f"Iscritti: {len(utenti)} · modalità {'LIVE' if live else 'PROVA (solo +test)'}{' · DRY' if dry else ''}")
    os.makedirs("anteprime", exist_ok=True)
    inviate = 0
    attesa = [u for u in utenti if u["settore"] != "Lavori edili"]
    if attesa:
        print(f"In lista d'attesa (settori non ancora attivi): {len(attesa)} · " +
              ", ".join(f"{k}: {v}" for k, v in Counter(u['settore'] for u in attesa).most_common()))
    for u in [u for u in utenti if u["settore"] == "Lavori edili"]:
        b, i, e, d = per_iscritto(avvisi, u)
        corpo, n = email_html(u, b, i, e, d, giorno)
        nome = u["email"].replace("@", "_at_")
        with open(f"anteprime/{nome}.html", "w") as f:
            f.write(corpo)
        print(f"  {u['email']}: {len(b)} bandi, {len(i)} indagini, {len(e)} elenchi, {len(d)} affid. diretti")
        if dry or (not live and "+test" not in u["email"]):
            continue
        oggetto = f"{n} occasioni per te oggi · {' '.join(u['soa'][:3]) or 'GaraPronta'}" if n else "GaraPronta · il punto di oggi"
        invia(key, u["email"], oggetto, corpo)
        inviate += 1
    print(f"Email inviate: {inviate}")


if __name__ == "__main__":
    main()
