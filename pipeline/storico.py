#!/usr/bin/env python3
"""Scarica lo storico ANAC giorno per giorno per un mese (MESE=AAAA-MM) e salva data/AAAA/MM/GG.json.gz.
Salta i giorni già salvati. Usa le stesse funzioni della pipeline giornaliera."""
import os, sys, calendar
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import garapronta as g

y, m = map(int, os.environ["MESE"].split("-"))
for d in range(1, calendar.monthrange(y, m)[1] + 1):
    giorno = date(y, m, d)
    if giorno >= date.today():
        break
    path = f"data/{giorno:%Y/%m/%d}.json.gz"
    if os.path.exists(path) and os.path.getsize(path) > 100:
        continue
    s = giorno.strftime("%d/%m/%Y")
    try:
        grezzi = g.scarica(s)
        g.salva(s, [g.estrai(a) for a in grezzi])
        print(f"{s}: {len(grezzi)} avvisi", flush=True)
    except Exception as e:
        print(f"{s}: ERRORE {e}", flush=True)
