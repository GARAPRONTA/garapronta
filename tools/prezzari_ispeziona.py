"""Sul server italiano: mostra la struttura dei prezzari XML (Abruzzo)."""
import glob, zipfile
for f in glob.glob("/opt/garapronta/prezzari/Abruzzo*.zip"):
    z = zipfile.ZipFile(f)
    d = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    print(len(d)); i = d.find("prodotto"); print(d[:1500]); print("....."); print(d[i - 200:i + 3500] if i > 0 else d[20000:23000])
