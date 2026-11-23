#!/usr/bin/env python3
"""Calcola dati/regioni.json dallo storico (ultimi 12 mesi): solo enti e numeri, nessun nome di impresa."""
import gzip, json, glob, os, sys, statistics
from collections import Counter, defaultdict
from datetime import date
sys.path.insert(0, 'pipeline'); import garapronta as g

files = sorted(glob.glob('data/20*/*/*.json.gz'))
oggi = date.today()
lim = date(oggi.year - 1, oggi.month, 1)
TETTO = {'Lavori': 150000, 'Servizi': 140000, 'Forniture': 140000}   # soglie affidamento diretto
R = defaultdict(lambda: {'ad': Counter(), 'ad_val': defaultdict(list), 'mesi': Counter(), 'enti': Counter(),
                         'cat': Counter(), 'ind': 0, 'bandi': 0, 'elenchi': 0, 'enti_set': set()})
for f in files:
    y, m, d = map(int, f[5:15].split('/')); 
    if date(y, m, d) < lim: continue
    for a in json.load(gzip.open(f, 'rt')):
        if a['tipo'] != 'avviso': continue
        t = a['tipologia']
        for it in a['items']:
            reg = g.regione(it)
            if not reg: continue
            for r in (reg, 'Italia'):
                x = R[r]; nat = it.get('natura') or ''
                if t == 'AFFIDAMENTI_DIRETTI_SOTTO_SOGLIA' and nat in TETTO:
                    x['ad'][nat] += 1
                    v = it.get('valore')
                    if v and 0 < v <= TETTO[nat]: x['ad_val'][nat].append(v)
                    if nat == 'Lavori':
                        x['mesi'][f'{y}-{m:02d}'] += 1
                        if a['ente']: x['enti'][__import__('re').sub(r'(\d)\?', r'\1°', a['ente'])] += 1
                        for c in it['cat']: x['cat'][c] += 1
                    if a['ente']: x['enti_set'].add(a['ente'])
                elif t == 'INDAGINI_DI_MERCATO_SOTTO_SOGLIA' and nat == 'Lavori': x['ind'] += 1
                elif t == 'BANDI' and nat == 'Lavori': x['bandi'] += 1
                elif t == 'ELENCHI_OPERATORI_ECONOMICI': x['elenchi'] += 1
out = {}
for r, x in R.items():
    lv = x['ad_val']['Lavori']
    out[r] = {
        'affidamenti': dict(x['ad']),
        'lavori_valore_stimato': round(sum(lv) * x['ad']['Lavori'] / max(1, len(lv))),
        'lavori_mediana': round(statistics.median(lv)) if lv else None,
        'mesi': dict(sorted(x['mesi'].items())),
        'top_enti': x['enti'].most_common(8),
        'top_categorie': x['cat'].most_common(6),
        'indagini_lavori': x['ind'], 'bandi_lavori': x['bandi'], 'elenchi': x['elenchi'],
        'enti_attivi': len(x['enti_set']),
    }
out['_periodo'] = f'{lim:%m/%Y} - {oggi:%m/%Y}'
json.dump(out, open('dati/regioni.json', 'w'), ensure_ascii=False, separators=(',', ':'))
it = out['Italia']; print(out['_periodo'], it['affidamenti'], it['lavori_valore_stimato'], it['lavori_mediana'], it['enti_attivi'])
print('Lazio', out['Lazio']['affidamenti'], out['Lazio']['top_enti'][:3], out['Lazio']['mesi'])
