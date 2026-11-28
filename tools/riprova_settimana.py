"""Riprova le gare non lette dei 6 giorni precedenti: molti enti caricano i documenti qualche giorno dopo l'avviso.
Le gare a inviti non si riprovano (i documenti non saranno mai pubblici)."""
import json, os, subprocess, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

oggi = datetime.now(ZoneInfo("Europe/Rome"))
for n in range(1, 8):
    d = oggi - timedelta(days=n)
    f = f"testi/{d:%Y/%m/%d}/rapporto.json"
    if not os.path.exists(f):
        continue
    falliti = [r["cig"] for r in json.load(open(f))
               if r["esito"] != "ok" and not r["esito"].startswith("documenti riservati")]
    if not falliti:
        continue
    print(f"== Riprovo {len(falliti)} gare del {d:%d/%m/%Y}", flush=True)
    subprocess.run([sys.executable, "pipeline/documenti.py"],
                   env={**os.environ, "DATA": f"{d:%d/%m/%Y}", "SOLO_CIG": ",".join(falliti)}, timeout=3000)
