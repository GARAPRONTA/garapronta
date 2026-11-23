import gzip, json, re, sys, urllib.request, collections
from urllib.parse import urljoin, urlparse
a = json.load(gzip.open(sys.argv[1], 'rt'))
righe = [(x, i) for x in a if x['tipo'] == 'avviso' and x['tipologia'] in ('BANDI', 'INDAGINI_DI_MERCATO_SOTTO_SOGLIA')
         for i in x['items'] if (i.get('natura') or '').lower() == 'lavori']
visti, esito, domini = set(), collections.Counter(), collections.Counter()
for x, i in righe:
    u = x.get('link')
    if not u or u in visti: continue
    visti.add(u)
    dom = urlparse(u).netloc; domini[dom] += 1
    try:
        req = urllib.request.Request(u, headers={'user-agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=25) as r:
            ct = r.headers.get('content-type', ''); body = r.read(3_000_000)
        if 'pdf' in ct: k = 'PDF diretto'
        else:
            t = body.decode('utf-8', 'ignore')
            pdf = set(re.findall(r'href=["\']([^"\']+\.(?:pdf|PDF|zip|p7m)[^"\']*)', t))
            login = bool(re.search(r'login|accedi|password|spid|registrazione', t, re.I))
            if pdf: k = f'pagina con {min(len(pdf),9)}+ file scaricabili'
            elif len(t) < 3000 or 'javascript' in t.lower() and not pdf: k = 'pagina dinamica (serve browser)'
            else: k = 'pagina senza file' + (' (con login)' if login else '')
    except Exception as e:
        k = 'errore ' + type(e).__name__
    esito[k.split(' con ')[0] if k.startswith('pagina con') else k] += 1
    print(f'{k:40} {dom}')
print('\nLINK UNICI:', len(visti)); print(dict(esito)); print('PIATTAFORME:', domini.most_common(12))
