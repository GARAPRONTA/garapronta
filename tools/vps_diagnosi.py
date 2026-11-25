"""Diagnosi sul server italiano: il progetto della Provincia di Teramo su Nextcloud si scarica?"""
import urllib.request, time
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
for u in ["https://cloud.provincia.teramo.it/index.php/s/6ftWZ7kp9CkeJjb",
          "https://cloud.provincia.teramo.it/index.php/s/6ftWZ7kp9CkeJjb/download"]:
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"user-agent": UA}), timeout=60)
        h = dict(r.headers); n = len(r.read(2_000_000))
        print(u, r.status, h.get("Content-Type"), h.get("Content-Length"), h.get("Content-Disposition"), "letti", n, f"{time.time()-t:.1f}s")
    except Exception as e:
        print(u, "ERR", e, f"{time.time()-t:.1f}s")
