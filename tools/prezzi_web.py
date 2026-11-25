"""Pagina 'Prezzi per i preventivi': dati compatti per regione (g/prezzi/<slug>.json.gz) + pagina di ricerca."""
import glob, gzip, json, os, re

os.makedirs("g/prezzi", exist_ok=True)
regioni = []
for f in sorted(glob.glob("indici/prezzari/*.json.gz")):
    j = json.load(gzip.open(f, "rt"))
    reg, anno, voci = j["regione"], j.get("anno", 2026), j["voci"]
    visti, righe = set(), []
    for k, (prezzo, um, descr) in voci.items():
        if re.fullmatch(r"\d+([.,]\d+)?", k) or not descr:
            continue
        chiave = (prezzo, descr)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe.append([k, descr, um, prezzo])
    slug = re.sub(r"[^a-z]+", "-", reg.lower()).strip("-")
    with gzip.open(f"g/prezzi/{slug}.json.gz", "wt", encoding="utf-8") as fo:
        json.dump(righe, fo, ensure_ascii=False, separators=(",", ":"))
    regioni.append({"nome": reg, "slug": slug, "anno": anno, "voci": len(righe)})
    print(reg, len(righe))
json.dump(regioni, open("g/prezzi/regioni.json", "w"), ensure_ascii=False)
