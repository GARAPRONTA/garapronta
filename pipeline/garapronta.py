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
            out.append({"email": c["email"], "soa": soa, "regione": (at.get("REGIONE") or "Tutta Italia").strip()})
        if len(cs) < 500:
            break
        off += 500
    return out


# ---------------------------------------------------------------- 3. scelta gare
def regione(it):
    return NUTS_REGIONE.get((it.get("nuts") or "")[:4])


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
    key = lambda r: -(r[1].get("valore") or 0)
    return sorted(bandi, key=key), sorted(indagini, key=key), elenchi[:5], diretti


# ---------------------------------------------------------------- 4. email
CSS_CARD = "background:#fff;border-radius:16px;padding:18px 20px;margin:0 0 12px;border:1px solid #e8e8ed"


def scad_txt(s):
    if not s:
        return ""
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        gg = (d.date() - datetime.now(timezone.utc).date()).days
        col = "#c2410c" if gg <= 10 else "#1d1d1f"
        return f'<span style="color:{col};font-weight:600">scade il {d:%d/%m} ({gg} giorni)</span>'
    except Exception:
        return ""


def scheda(a, it, soa, tipo):
    cats = ", ".join(it["cat"]) or "categoria n.d."
    if tipo == "indagine":
        badge = '<span style="background:#e8f1ff;color:#007aff;border-radius:99px;padding:3px 9px;font-size:12px;font-weight:600">Candidati per essere invitato</span>'
    else:
        manca = [c for c in it["cat"] if c not in soa] if soa and "ALTRA" not in soa else []
        badge = ('<span style="background:#e7f6ee;color:#1f9d55;border-radius:99px;padding:3px 9px;font-size:12px;font-weight:600">✓ Hai le categorie</span>'
                 if not manca else
                 f'<span style="background:#fdeee6;color:#c2410c;border-radius:99px;padding:3px 9px;font-size:12px;font-weight:600">Ti serve un partner {", ".join(manca)}</span>')
    rib = ""
    if tipo == "bando":
        r = next((RIBASSO[c] for c in it["cat"] if c in RIBASSO), RIBASSO_TUTTI)
        rib = f' · ribasso vincente tipico <b>{str(r).replace(".", ",")}%</b>'
    link = a.get("link") or SITE
    titolo = html.escape((a["titolo"] or it["descr"] or "Lavori")[:140])
    return f'''<div style="{CSS_CARD}">
<div style="font-size:12px;color:#6e6e73;margin-bottom:4px">{html.escape(a["ente"] or "")} · {html.escape(regione(it) or "")}</div>
<div style="font-size:16px;font-weight:650;line-height:1.3;margin-bottom:6px">{titolo}</div>
<div style="font-size:14px;color:#1d1d1f;margin-bottom:8px"><b>{euro(it.get("valore"))}</b> · {html.escape(cats)} · {scad_txt(it.get("scadenza") or a.get("scadenza"))}{rib}</div>
<div style="margin-bottom:10px">{badge}</div>
<a href="{html.escape(link)}" style="color:#007aff;font-weight:600;font-size:14px;text-decoration:none">Apri i documenti ufficiali →</a>
<span style="font-size:11px;color:#86868b;margin-left:8px">CIG {html.escape(it.get("cig") or "")}</span>
</div>'''


def riepilogo_diretti(diretti, u):
    if not diretti:
        return ""
    tot = sum(it.get("valore") or 0 for _, it in diretti)
    enti = Counter(a["ente"] for a, _ in diretti if a["ente"]).most_common(3)
    zona = "in Italia" if u["regione"].lower() in ("tutta italia", "") else f"in {u['regione']}"
    righe = "".join(f"<li>{html.escape(e)}: {n} lavori</li>" for e, n in enti)
    return f'''<div style="{CSS_CARD}">
<div style="font-size:16px;font-weight:650;margin-bottom:6px">Lavori affidati senza gara {zona}</div>
<div style="font-size:14px;color:#1d1d1f">Ieri <b>{len(diretti)}</b> lavori affidati direttamente, per <b>{euro(tot)}</b>. Gli enti che ne hanno affidati di più:</div>
<ul style="font-size:14px;margin:8px 0 0;padding-left:18px">{righe}</ul>
<div style="font-size:12px;color:#6e6e73;margin-top:8px">Questi enti scelgono le imprese da elenchi e indagini di mercato: iscriversi ai loro elenchi è il primo passo per essere chiamati.</div>
</div>'''


def email_html(u, bandi, indagini, elenchi, diretti, giorno):
    soa = set(u["soa"])
    blocchi = []
    if indagini:
        blocchi.append('<h2 style="font-size:18px;margin:26px 0 10px">Fatti invitare</h2>' +
                       "".join(scheda(a, it, soa, "indagine") for a, it in indagini[:8]))
    if bandi:
        blocchi.append('<h2 style="font-size:18px;margin:26px 0 10px">Gare aperte per te</h2>' +
                       "".join(scheda(a, it, soa, "bando") for a, it in bandi[:10]))
    if elenchi:
        blocchi.append('<h2 style="font-size:18px;margin:26px 0 10px">Elenchi di imprese aperti</h2>' +
                       "".join(f'<div style="{CSS_CARD}"><b>{html.escape(a["ente"])}</b><br>'
                               f'<span style="font-size:14px">{html.escape((a["titolo"] or it["descr"])[:140])}</span><br>'
                               f'<a href="{html.escape(a.get("link") or SITE)}" style="color:#007aff;font-size:14px;font-weight:600;text-decoration:none">Come iscriversi →</a></div>'
                               for a, it in elenchi))
    blocchi.append(riepilogo_diretti(diretti, u))
    if not (indagini or bandi or elenchi):
        blocchi.insert(0, f'<div style="{CSS_CARD}">Ieri nessuna gara nuova per le tue categorie nella tua zona. Ti scriviamo appena esce.</div>')
    n = len(bandi) + len(indagini)
    profilo = f'{", ".join(u["soa"]) or "tutte le categorie"} · {u["regione"]}'
    return f'''<!DOCTYPE html><html><body style="margin:0;background:#f5f5f7;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1d1d1f">
<div style="max-width:620px;margin:0 auto;padding:24px 16px">
<div style="font-size:17px;font-weight:650;margin-bottom:18px">● GaraPronta</div>
<h1 style="font-size:28px;letter-spacing:-.02em;margin:0 0 6px">{n} occasioni per te</h1>
<div style="color:#6e6e73;font-size:14px;margin-bottom:8px">Pubblicate il {giorno} · {html.escape(profilo)}</div>
{"".join(blocchi)}
<div style="font-size:12px;color:#86868b;margin-top:26px;line-height:1.5">Fonte: Piattaforma di pubblicità legale ANAC (dati CC BY 4.0). Controlla sempre i requisiti sui documenti ufficiali.
Il ribasso tipico è la mediana dei ribassi vincenti in gare simili: è un dato di mercato, non un consiglio d'offerta.<br>
Ricevi questa email perché ti sei iscritto a GaraPronta. <a href="mailto:garapronta@gmail.com?subject=Disiscrivimi" style="color:#86868b">Disiscriviti</a></div>
</div></body></html>''', n


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
    for u in utenti:
        b, i, e, d = per_iscritto(avvisi, u)
        corpo, n = email_html(u, b, i, e, d, giorno)
        nome = u["email"].replace("@", "_at_")
        with open(f"anteprime/{nome}.html", "w") as f:
            f.write(corpo)
        print(f"  {u['email']}: {len(b)} bandi, {len(i)} indagini, {len(e)} elenchi, {len(d)} affid. diretti")
        if dry or (not live and "+test" not in u["email"]):
            continue
        oggetto = f"{n} gare e inviti per te · {', '.join(u['soa'][:3]) or 'GaraPronta'}" if n else "GaraPronta · il punto di oggi"
        invia(key, u["email"], oggetto, corpo)
        inviate += 1
    print(f"Email inviate: {inviate}")


if __name__ == "__main__":
    main()
