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
            "descr": pulisci(it.get("descrizione"))[:300],
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
        "titolo": pulisci((t.get("metadata") or {}).get("titolo"))[:300],
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

    bandi, indagini, elenchi, diretti = [], [], [], []
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
    return sorted(bandi, key=key), sorted(indagini, key=key), elenchi[:5], diretti


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
        rib = barra_ribasso(next((RIBASSO[c] for c in it["cat"] if c in RIBASSO), RIBASSO_TUTTI))
    t = frase(a["titolo"] or it["descr"] or "Lavori")
    titolo = html.escape(t[:130] + ("…" if len(t) > 130 else ""))
    link = html.escape(a.get("link") or SITE)
    com = it.get("istat") and str(it["istat"]).title()
    if com and com.lower() in (a.get("ente") or "").lower():
        com = None
    luogo = " · ".join(x for x in [com, regione(it)] if x)
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px;background:#ffffff;border-radius:22px;border:1px solid #ececf0">
<tr><td style="padding:20px 22px;border-left:4px solid {accento};border-radius:22px">
<div style="font-size:12px;color:{INK3};margin-bottom:6px">{html.escape((a['ente'] or '')[:70])}{(' · ' + html.escape(luogo)) if luogo else ''}</div>
<div style="font-size:17px;font-weight:650;line-height:1.3;color:{INK};letter-spacing:-.01em;margin-bottom:12px">{titolo}</div>
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:26px;font-weight:700;letter-spacing:-.03em;color:{INK};padding-right:14px">{euro(it.get('valore'))}</td>
<td style="font-size:12px;color:{INK2}">{html.escape(cats)}</td></tr></table>
<div style="margin-top:12px">{badge} &nbsp;{scad_pill(it.get('scadenza') or a.get('scadenza'))}</div>
{rib}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:16px"><tr>
<td style="background:{BLU};border-radius:999px"><a href="{link}" style="display:inline-block;padding:10px 18px;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none">Apri i documenti</a></td>
<td style="padding-left:12px;font-size:11px;color:{INK3}">CIG {html.escape(it.get('cig') or '')}</td></tr></table>
</td></tr></table>"""


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
<div style="font-size:13px;color:{INK2};margin:4px 0 12px">{html.escape(frase(a['titolo'] or it['descr'])[:140])}</div>
<a href="{html.escape(a.get('link') or SITE)}" style="color:{BLU};font-size:14px;font-weight:600;text-decoration:none">Come iscriversi →</a></td></tr></table>""" for a, it in elenchi))
    blocchi.append(riepilogo_diretti(diretti, u))
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
Il ribasso tipico è la mediana dei ribassi vincenti in gare simili: è un dato di mercato, non un consiglio d'offerta.<br>
Ricevi questa email perché ti sei iscritto a GaraPronta · <a href="mailto:garapronta@gmail.com?subject=Disiscrivimi" style="color:{INK3}">Disiscriviti</a></div>
</td></tr></table></td></tr></table></body></html>"""
    return corpo, n


def invia(key, to, oggetto, corpo):
    return http_json(f"{BREVO}/smtp/email", headers={"api-key": key}, method="POST", data={
        "sender": SENDER, "to": [{"email": to}], "subject": oggetto, "htmlContent": corpo,
        "tags": ["garapronta-giornaliera"]})


# ---------------------------------------------------------------- main
def main():
    giorno = os.environ.get("DATA") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d/%m/%Y")
    print(f"== Giorno {giorno}")
    grezzi = scarica(giorno)
    avvisi = [estrai(a) for a in grezzi]
    path = salva(giorno, avvisi)
    print(f"Scaricati {len(grezzi)} avvisi, salvati in {path}")
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
