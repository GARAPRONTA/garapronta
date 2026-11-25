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
import gzip, html, json, os, sys, time, urllib.request, urllib.error
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
def iscritti(key, lista):
    out, off = [], 0
    while True:
        j = http_json(f"{BREVO}/contacts/lists/{lista}/contacts?limit=500&offset={off}", headers={"api-key": key})
        cs = j.get("contacts") or []
        for c in cs:
            at = c.get("attributes") or {}
            soa = [s.strip().upper().replace("OG", "OG ").replace("OS", "OS ").replace("  ", " ")
                   for s in (at.get("SOA") or "").split(",") if s.strip()]
            out.append({"email": c["email"], "soa": soa, "regione": (at.get("REGIONE") or "Tutta Italia").strip(),
                        "settore": (at.get("SETTORE") or "Lavori edili").strip()})
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

    def zona_ok(it):
        return tutta or regione(it) == u["regione"]

    def cat_ok(it):
        return altro or not it["cat"] or soa & set(it["cat"])

    bandi, indagini, elenchi, diretti, esiti = [], [], [], [], []
    for a in avvisi:
        if a["tipo"] != "avviso":
            continue
        for it in a["items"]:
            if (it.get("natura") or "").lower() != "lavori" and a["tipologia"] != "ELENCHI_OPERATORI_ECONOMICI":
                continue
            if not zona_ok(it):
                continue
            riga = (a, it)
            if a["tipologia"] == "BANDI" and cat_ok(it):
                bandi.append(riga)
            elif a["tipologia"] == "INDAGINI_DI_MERCATO_SOTTO_SOGLIA" and cat_ok(it):
                indagini.append(riga)
            elif a["tipologia"] == "ELENCHI_OPERATORI_ECONOMICI":
                elenchi.append(riga)
            elif a["tipologia"] == "AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA":
                diretti.append(riga)
            elif a["tipologia"] == "RISULTATI" and it.get("aggiudicatari") and cat_ok(it):
                esiti.append(riga)
    oggi = datetime.now(timezone.utc).date()

    def aperta(r):
        a, it = r
        s = it.get("scadenza") or a.get("scadenza")
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date() >= oggi
        except Exception:
            return True
    key = lambda r: -(r[1].get("valore") or 0)
    bandi = [r for r in bandi if aperta(r)]
    indagini = [r for r in indagini if aperta(r)]
    PER_ISCRITTO_EXTRA["esiti"] = sorted(esiti, key=key)
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
    """Nei contenuti pubblici (schede web) solo nomi di societa', mai ditte individuali."""
    parti = [x.strip() for x in (nome or "").split("+")]
    return " + ".join(x if SOCIETA.search(x) else "impresa individuale" for x in parti if x)


def storico(a, it):
    """Ribassi vincenti per questa gara: stesso ente e categoria; se pochi dati, regione; poi Italia."""
    R, E = _indici()
    if not R:
        return None
    cats = [c.replace(" ", "") for c in it.get("cat") or []]
    if not cats:
        return None
    c = cats[0]
    ente = E.get(_nome(a.get("ente")))
    s = (R.get("ente", {}).get(ente["cf"], {}).get(c) if ente else None)
    if s and s["n"] >= 3:
        return {**s, "livello": "ente", "dove": a.get("ente"), "cat": c}
    reg = _nome(regione(it) or "")
    for k, v in (R.get("regione") or {}).items():
        if _nome(k).replace(" ", "") == reg.replace(" ", "") and c in v and v[c]["n"] >= 10:
            out = {**v[c], "livello": "regione", "dove": regione(it), "cat": c}
            if s:
                out["ente_poche"] = s
            return out
    v = (R.get("italia") or {}).get(c)
    return {**v, "livello": "italia", "dove": "Italia", "cat": c} if v and v["n"] >= 10 else None


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
        mese = f" · più attivo a {MESI_IT[int(e['mese']) - 1]}" if e.get("mese") else ""
        righe += f"""<tr><td style="padding:12px 0;border-top:1px solid #f0f0f3">
<div style="font-size:14px;font-weight:650;color:{INK}">{html.escape(titolo_ente(e['ente']))} <span style="font-weight:400;color:{INK3};font-size:12px">{html.escape(titolo_ente(e.get('prov') or ''))}</span></div>
<div style="font-size:13px;color:{INK2};margin-top:3px">{e['dir'] + e['neg']} lavori senza bando in 3 anni ({e['dir']} diretti, {e['neg']} su invito) · {html.escape(frase_rotazione(e))}{mese}</div>
<div style="font-size:13px;margin-top:5px">{' &nbsp;·&nbsp; '.join(extra)}</div></td></tr>"""
    return titolo_sezione("Enti da conoscere", "Chi affida i tuoi lavori senza bando",
                          f"{', '.join(c.replace(' ', '') for c in cats)} in {reg}, ultimi 3 anni. Farsi conoscere da questi enti è la strada per essere invitati.") + f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:22px;border:1px solid #ececf0"><tr><td style="padding:4px 22px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe}</table>
<div style="margin-top:12px"><a href="{url_mappa(reg, cats)}" style="font-size:14px;font-weight:600;color:{BLU};text-decoration:none">▸ Vedi tutti gli enti della tua zona</a></div>
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


def virgola(x):
    return str(x).replace(".", ",")


def blocco_storico(st):
    """Riquadro nell'email: quanto ribassa chi vince da questo ente."""
    if not st:
        return ""
    dove = {"ente": "questo ente", "regione": f"in {st['dove']}", "italia": "in Italia"}[st["livello"]]
    w1, w2 = max(2, min(98, round(st["p25"] / 40 * 100))), max(4, min(100, round(st["p75"] / 40 * 100)))
    off = f" · in media {round(st['off'])} offerte" if st.get("off") else ""
    return f"""<div style="margin-top:14px;background:#f5f5f7;border-radius:14px;padding:12px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:12px;color:{INK2}">Ribasso che vince · {st['cat']} {dove}</td>
<td align="right" style="font-size:15px;font-weight:700;color:{INK}">{virgola(st['med'])}%</td></tr></table>
<div style="position:relative;height:8px;background:#e3e3e8;border-radius:99px;margin:8px 0 6px">
<div style="margin-left:{w1}%;width:{max(3, w2 - w1)}%;height:8px;background:{BLU};border-radius:99px"></div></div>
<div style="font-size:11px;color:{INK3}">Metà delle gare vinte tra {virgola(st['p25'])}% e {virgola(st['p75'])}% · {st['n']} gare 2023-2025{off}</div></div>"""


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
        if not manca:
            badge, accento = pill("✓ Puoi partecipare", "#1f9d55", "#e7f6ee"), "#34c759"
        else:
            badge = pill(f"Ti serve un partner {', '.join(manca[:3])}{' +' if len(manca) > 3 else ''}", "#c2410c", "#fdeee6")
            accento = "#ff9f0a"
    rib = ""
    if tipo == "bando":
        st = storico(a, it)
        rib = blocco_storico(st) if st else barra_ribasso(next((RIBASSO[c] for c in it["cat"] if c in RIBASSO), RIBASSO_TUTTI))
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
<div style="font-size:12px;color:{INK3};margin-bottom:6px">{html.escape((a['ente'] or '')[:70])}{(' · ' + html.escape(luogo)) if luogo else ''}</div>
<div style="font-size:17px;font-weight:650;line-height:1.3;color:{INK};letter-spacing:-.01em;margin-bottom:12px">{titolo}</div>
{oggetto}{cosa}<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:26px;font-weight:700;letter-spacing:-.03em;color:{INK};padding-right:14px">{euro(it.get('valore'))}</td>
<td style="font-size:12px;color:{INK2}">{html.escape(cats)}</td></tr></table>
<div style="margin-top:12px">{badge} &nbsp;{scad_pill(it.get('scadenza') or a.get('scadenza'))}</div>
{rib}
{breve}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:16px"><tr>
<td style="background:{BLU};border-radius:999px"><a href="{link}" style="display:inline-block;padding:10px 18px;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none">Apri i documenti</a></td>
<td style="padding-left:12px;font-size:11px;color:{INK3}">CIG {html.escape(it.get('cig') or '')}</td></tr></table>
</td></tr></table>"""


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
    st = storico(a, it)
    blocco_st = ""
    if st:
        dove = {"ente": e(a.get("ente") or "questo ente"), "regione": "in " + e(st["dove"]), "italia": "in Italia"}[st["livello"]]
        righe = "".join(f'<tr><td>{e(x["d"])}</td><td>{e(frase(x["g"]))}</td><td style="text-align:right">{euro(x["i"]) if x["i"] else "—"}</td>'
                        f'<td style="text-align:right"><b>{virgola(x["r"])}%</b></td><td style="text-align:right">{x["o"] or "—"}</td><td>{e(pubblico(x["v"]))}</td></tr>'
                        for x in (st.get("ultime") or (st.get("ente_poche") or {}).get("ultime") or []))
        tab = (f'<h2>Le ultime gare {st["cat"]} di {e(a.get("ente") or "questo ente")}</h2><div style="overflow-x:auto"><table class="u"><tr><th>Mese</th><th>Oggetto</th><th>Base</th><th>Ribasso</th><th>Offerte</th><th>Vincitore</th></tr>{righe}</table></div>') if righe else ""
        blocco_st = f"""<div class="card"><h2 style="margin-top:0;color:#007aff">Quanto si ribassa per vincere</h2>
<div class="imp">{virgola(st['med'])}%</div><p class="uff">Ribasso mediano delle gare {st['cat']} vinte {dove} (2023-2025). Metà delle gare tra <b>{virgola(st['p25'])}%</b> e <b>{virgola(st['p75'])}%</b> · {st['n']} gare{(' · in media ' + str(round(st['off'])) + ' offerte') if st.get('off') else ''}.</p>
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
    blocchi = [head]
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
