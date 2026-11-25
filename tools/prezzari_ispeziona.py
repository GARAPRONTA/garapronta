"""Sul server italiano: struttura degli XML della piattaforma comune (Campania, Piemonte, Sardegna)."""
import glob, zipfile, re
for f in glob.glob("/opt/garapronta/prezzari/Campania_2026*.zip") + glob.glob("/opt/garapronta/prezzari/Piemonte_2026*.zip"):
    z = zipfile.ZipFile(f)
    print("\n##", f, [(n, z.getinfo(n).file_size) for n in z.namelist()][:12])
    n = max(z.namelist(), key=lambda x: z.getinfo(x).file_size)
    d = z.read(n).decode("utf-8", "ignore")
    i = max(d.find("<Articolo"), d.find("<articolo"), d.find("Prezzo"), d.find("prezzo"))
    print(d[:800]); print("....."); print(d[max(0, i - 1500):i + 1500])
