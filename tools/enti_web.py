"""Dai dati PVL salvati: per ogni ente, la piattaforma dove pubblica le gare e gli elenchi di imprese aperti.
Scrive indici/enti_web.json.gz  {nome_normalizzato: {"piatt": url_base, "elenchi": [...]}}"""
import gzip, json, glob, re, sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

sys.path.insert(0, "pipeline")
from garapronta import _nome, pulito  # noqa: E402

GENERICI = ("anticorruzione.it", "acquistinretepa.it", "google.", "gazzettaufficiale", "ted.europa")
dom, base, elenchi = defaultdict(Counter), {}, defaultdict(list)
for f in sorted(glob.glob("data/*/*/*.json.gz")):
    for a in json.load(gzip.open(f, "rt")):
        if a.get("tipo") != "avviso" or not a.get("ente"):
            continue
        k = _nome(a["ente"])
        link = (a.get("link") or "").strip()
        try:
            u = urlparse(link) if link.startswith("http") else None
        except ValueError:
            u = None
        if u:
            d = u.netloc.lower()
            if d and not any(g in d for g in GENERICI):
                dom[k][d] += 1
                base.setdefault((k, d), f"{u.scheme}://{d}/")
        if a["tipologia"] == "ELENCHI_OPERATORI_ECONOMICI":
            it = (a.get("items") or [{}])[0]
            elenchi[k].append({"t": pulito(a.get("titolo") or it.get("descr") or "Elenco operatori economici")[:160],
                               "link": link, "data": (a.get("pubblicato") or "")[:10],
                               "nat": it.get("natura"), "scad": a.get("scadenza")})
out = {}
for k in set(dom) | set(elenchi):
    r = {}
    if dom.get(k):
        d = dom[k].most_common(1)[0][0]
        r["piatt"] = base[(k, d)]
    if elenchi.get(k):
        r["elenchi"] = sorted(elenchi[k], key=lambda x: x["data"], reverse=True)[:5]
    out[k] = r
with gzip.open("indici/enti_web.json.gz", "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print("enti:", len(out), "con piattaforma:", sum(1 for v in out.values() if "piatt" in v),
      "con elenchi:", sum(1 for v in out.values() if "elenchi" in v))
