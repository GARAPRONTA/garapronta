"""Scrive docs/progetto/09_COPERTURA.md: quante gare di lavori hanno i documenti letti, per piattaforma, ultimi 30 giorni."""
import glob, json, os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

limite = (datetime.now() - timedelta(days=31)).strftime("%Y/%m/%d")
tot, per, persi = Counter(), defaultdict(Counter), []
giorni = 0
for f in sorted(glob.glob("testi/*/*/*/rapporto.json")):
    g = "/".join(f.split("/")[1:4])
    if g < limite:
        continue
    giorni += 1
    for r in json.load(open(f)):
        e = r["esito"].split(" (")[0]
        tot[e] += 1
        per[r.get("piattaforma") or "?"][e] += 1
        if e != "ok":
            persi.append((g, r["cig"], r.get("piattaforma") or "?", r["esito"], r["url"]))
n = sum(tot.values())
ris = tot["documenti riservati agli invitati"]
righe = [f"# Copertura documenti di gara (aggiornata da sola ogni mattina)", "",
         f"Ultimo aggiornamento: {datetime.now():%d/%m/%Y %H:%M} · {giorni} giorni · {n} gare di lavori (bandi e indagini).", "",
         f"- **Lette con i documenti: {tot['ok']} su {n} ({tot['ok'] / max(1, n):.0%})**",
         f"- Sulle gare con documenti pubblici (escluse {ris} a inviti): **{tot['ok'] / max(1, n - ris):.0%}**", "",
         "## Esiti", "", "| Esito | Gare |", "|---|---|"]
righe += [f"| {e} | {c} |" for e, c in tot.most_common()]
righe += ["", "## Piattaforme con più gare perse", "", "| Piattaforma | Lette | Perse | Motivi |", "|---|---|---|---|"]
for p, c in sorted(per.items(), key=lambda x: -(sum(x[1].values()) - x[1]["ok"]))[:30]:
    perse = sum(c.values()) - c["ok"]
    if perse:
        motivi = ", ".join(f"{e} {k}" for e, k in c.most_common() if e != "ok")
        righe.append(f"| {p} | {c['ok']} | {perse} | {motivi} |")
righe += ["", "## Ultime gare perse (più recenti prima)", "", "| Giorno | CIG | Piattaforma | Esito | Link |", "|---|---|---|---|---|"]
for g, cig, p, e, u in sorted(persi, reverse=True)[:80]:
    righe.append(f"| {g} | {cig} | {p} | {e} | {u[:90]} |")
os.makedirs("docs/progetto", exist_ok=True)
open("docs/progetto/09_COPERTURA.md", "w").write("\n".join(righe) + "\n")
print("\n".join(righe[:8]))
