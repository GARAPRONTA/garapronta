"""Esplora i cataloghi open data pubblici (ANAC e MIT): dataset utili e intestazioni dei CSV."""
import json, urllib.request, io, zipfile
UA = {"user-agent": "Mozilla/5.0 GaraPronta-ricerca"}

def get(u, n=None):
    req = urllib.request.Request(u, headers={**UA, **({"range": f"bytes=0-{n}"} if n else {})})
    return urllib.request.urlopen(req, timeout=60).read()

def ckan(base, azione):
    try:
        return json.loads(get(f"{base}/api/3/action/{azione}"))["result"]
    except Exception as e:
        print("ERR", base, azione, e); return None

A = "https://dati.anticorruzione.it/opendata"
lista = ckan(A, "package_list") or []
print("ANAC dataset:", len(lista)); print(", ".join(lista))
for nome in lista:
    if not any(k in nome for k in ("aggiudica", "partecip", "programm", "stazioni", "cig-20", "ocds-appalti-ordinari-2025", "variant", "subappalt", "fine-contratto", "pubblicazioni", "lavorazioni", "categorie", "quadro")):
        continue
    p = ckan(A, f"package_show?id={nome}")
    if not p: continue
    print(f"\n### {nome}: {p.get('title')} | aggiornato {p.get('metadata_modified','')[:10]}")
    for r in (p.get("resources") or [])[:6]:
        u = r.get("url", "")
        print("  -", r.get("format"), r.get("name"), u)
    # intestazione del primo CSV/zip
    for r in p.get("resources") or []:
        u = r.get("url", "")
        try:
            if u.endswith(".csv"):
                print("  campi:", get(u, 3000).decode("utf-8", "ignore").splitlines()[0][:1500]); break
            if u.endswith(".zip") and "csv" in (r.get("format") or "").lower() + u.lower():
                b = get(u)
                z = zipfile.ZipFile(io.BytesIO(b)); f = z.namelist()[0]
                print("  campi:", z.open(f).readline().decode("utf-8", "ignore")[:1500], "| MB", len(b) // 1e6); break
        except Exception as e:
            print("  campi: ERR", e); break

M = "https://dati.mit.gov.it/catalog"
for q in ("programma triennale", "programmi", "scp"):
    r = ckan(M, f"package_search?q={urllib.parse.quote(q)}&rows=10") if hasattr(urllib, "parse") else None
import urllib.parse
for q in ("programma triennale", "programmi lavori"):
    r = ckan(M, f"package_search?q={urllib.parse.quote(q)}&rows=10")
    for p in (r or {}).get("results", []):
        print(f"\nMIT {p['name']}: {p.get('title')}")
        for x in p.get("resources", [])[:8]:
            print("  -", x.get("format"), x.get("name"), x.get("url"))
