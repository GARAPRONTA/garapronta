"""Diagnosi sul server italiano: contenuto dell'archivio del progetto della Provincia di Teramo."""
import io, sys, urllib.request, zipfile
sys.path.insert(0, "/opt/garapronta")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
d = urllib.request.urlopen(urllib.request.Request("https://cloud.provincia.teramo.it/index.php/s/6ftWZ7kp9CkeJjb/download", headers={"user-agent": UA}), timeout=300).read()
print("MB", len(d) // 1e6, d[:4])
z = zipfile.ZipFile(io.BytesIO(d))
for i in z.infolist()[:80]:
    print(f"  {i.file_size // 1024:7} KB  {i.filename}")
import documenti
fs = documenti.espandi([("AMBITO B.zip", d)])
print("dopo espandi:", [(n, len(b)) for n, b in fs][:40])
