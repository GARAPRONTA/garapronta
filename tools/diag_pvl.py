"""Diagnosi: nei dati grezzi della PVL ANAC, quali link ci sono per ogni gara (oltre a quello che usiamo)?
Salva diag/pvl_link.json con tutti i valori http trovati nei template delle gare non lette."""
import json, glob, re, sys, urllib.request
sys.path.insert(0, "pipeline")
import garapronta as g
falliti = {}
for f in glob.glob("testi/2026/11/*/rapporto.json"):
    for r in json.load(open(f)):
        if r["esito"] != "ok":
            falliti[r["cig"]] = (f.split("/")[3], r["esito"], r["url"])
giorni = sorted({v[0] for v in falliti.values()})
out = {}
def http_di(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from http_di(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from http_di(v, f"{path}[{i}]")
    elif isinstance(x, str) and re.search(r"https?://|www\.", x):
        yield path, x
for gg in giorni:
    for a in g.scarica(f"{gg}/11/2026"):
        s = json.dumps(a)
        for cig in [c for c in falliti if c in s]:
            out[cig] = {"esito": falliti[cig][1], "usato": falliti[cig][2], "link": list(http_di(a))[:40]}
    print(gg, len(out), flush=True)
json.dump(out, open("diag/pvl_link.json", "w"), ensure_ascii=False, indent=1)
