"""Banca dati GaraPronta (gira sul server italiano, perché ANAC blocca gli IP esteri).

Scarica i dataset aperti ANAC (CC BY-SA 4.0), li unisce con DuckDB e produce gli indici usati da email e schede:
  indici/ribassi.json.gz  -> per ente+categoria e per provincia+categoria: ribassi vincenti, offerte, ultimi esiti
  indici/enti.json.gz     -> nome ente normalizzato -> codice fiscale, provincia
"""
import gzip, json, os, re, subprocess, sys, time, urllib.request, zipfile
from datetime import date

import duckdb

B = "https://dati.anticorruzione.it/opendata/download/dataset"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
D = "/opt/garapronta/anac"
OUT = "/opt/garapronta/indici"
ANNI = [2023, 2024, 2025]
os.makedirs(D, exist_ok=True); os.makedirs(OUT, exist_ok=True); os.makedirs(f"{D}/csv", exist_ok=True)


def scarica(percorso, forza=False):
    nome = os.path.basename(percorso)
    dest = f"{D}/{nome}"
    if os.path.exists(dest) and os.path.getsize(dest) > 1000 and not forza:
        return dest
    for t in range(3):
        try:
            req = urllib.request.Request(f"{B}/{percorso}", headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=900) as r, open(dest + ".tmp", "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            os.replace(dest + ".tmp", dest)
            return dest
        except Exception as e:
            print("  riprovo", nome, e, flush=True); time.sleep(10)
    return None


def estrai(zp):
    """Scompatta il CSV del file zip in csv/ (una volta sola)."""
    with zipfile.ZipFile(zp) as z:
        n = [x for x in z.namelist() if x.endswith(".csv")][0]
        dest = f"{D}/csv/{os.path.basename(zp)[:-4]}.csv"
        if not os.path.exists(dest):
            with z.open(n) as src, open(dest, "wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
        return dest


def norm(s):
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s.replace("'", " "))
    return re.sub(r"\s+", " ", s).strip()


t0 = time.time()
print("== download", flush=True)
cig_csv = []
for anno in ANNI:
    for m in range(1, 13):
        z = scarica(f"cig-{anno}/filesystem/cig_csv_{anno}_{m:02d}.zip")
        if z:
            cig_csv.append(estrai(z))
print(f"  CIG: {len(cig_csv)} file mensili", flush=True)
agg = estrai(scarica("aggiudicazioni/filesystem/aggiudicazioni_csv.zip", forza=True))
aggi = estrai(scarica("aggiudicatari/filesystem/aggiudicatari_csv.zip", forza=True))
cat = estrai(scarica("categorie-opera/filesystem/categorie-opera_csv.zip", forza=True))
print(f"  scaricato in {time.time() - t0:.0f}s", flush=True)

con = duckdb.connect(f"{D}/banca.duckdb")
con.execute("SET memory_limit='1200MB'; SET threads=2; SET temp_directory='/opt/garapronta/anac/tmp'; SET preserve_insertion_order=false")
OPZ = "delim=';', quote='\"', header=true, all_varchar=true, ignore_errors=true"

print("== tabelle", flush=True)
lista = ", ".join(f"'{x}'" for x in cig_csv)
con.execute(f"""
CREATE OR REPLACE TABLE lavori AS
SELECT cig, any_value(cf_amministrazione_appaltante) cf, any_value(denominazione_amministrazione_appaltante) ente,
       any_value(provincia) provincia, any_value(TRY_CAST(importo_lotto AS DOUBLE)) importo,
       any_value(tipo_scelta_contraente) procedura, any_value(TRY_CAST(data_pubblicazione AS DATE)) data_pub,
       any_value(oggetto_lotto) oggetto
FROM read_csv([{lista}], {OPZ}, union_by_name=true)
WHERE oggetto_principale_contratto = 'LAVORI'
GROUP BY cig""")
print("  lavori:", con.execute("select count(*) from lavori").fetchone(), flush=True)
con.execute(f"""
CREATE OR REPLACE TABLE cat AS
SELECT cig, replace(any_value(id_categoria), ' ', '') cat
FROM read_csv('{cat}', {OPZ}) WHERE cod_tipo_categoria = 'P' AND cig IN (SELECT cig FROM lavori) GROUP BY cig""")
con.execute(f"""
CREATE OR REPLACE TABLE agg AS
SELECT cig, id_aggiudicazione id, TRY_CAST(ribasso_aggiudicazione AS DOUBLE) rib,
       TRY_CAST(numero_offerte_ammesse AS INTEGER) offerte, TRY_CAST(num_imprese_offerenti AS INTEGER) offerenti,
       TRY_CAST(num_imprese_invitate AS INTEGER) invitate, TRY_CAST(importo_aggiudicazione AS DOUBLE) imp_agg,
       TRY_CAST(data_aggiudicazione_definitiva AS DATE) data_agg, criterio_aggiudicazione criterio
FROM read_csv('{agg}', {OPZ})
WHERE esito = 'AGGIUDICATA' AND cig IN (SELECT cig FROM lavori)""")
con.execute(f"""
CREATE OR REPLACE TABLE vinc AS
SELECT id_aggiudicazione id, string_agg(DISTINCT denominazione, ' + ') vincitori
FROM read_csv('{aggi}', {OPZ}) WHERE id_aggiudicazione IN (SELECT id FROM agg) GROUP BY id_aggiudicazione""")

# Gare con concorrenza vera (no affidamenti diretti), ribasso plausibile
con.execute("""
CREATE OR REPLACE TABLE esiti AS
SELECT l.cig, l.cf, l.ente, l.provincia, c.cat, l.importo, l.procedura, l.oggetto, a.rib, a.offerte, a.offerenti,
       a.invitate, a.imp_agg, a.data_agg, a.criterio, v.vincitori
FROM agg a JOIN lavori l USING (cig) LEFT JOIN cat c USING (cig) LEFT JOIN vinc v ON v.id = a.id
WHERE a.rib > 0 AND a.rib < 60 AND l.procedura NOT ILIKE '%AFFIDAMENTO DIRETTO%'""")
print("  esiti con ribasso:", con.execute("select count(*), count(distinct cf), median(rib) from esiti").fetchone(), flush=True)


def stats(chiave):
    q = f"""
    SELECT {chiave}, cat, count(*) n, round(median(rib), 2) med, round(quantile_cont(rib, 0.25), 2) p25,
           round(quantile_cont(rib, 0.75), 2) p75, round(avg(coalesce(offerenti, offerte)), 1) offerenti,
           max(data_agg) ultima,
           list(struct_pack(d := strftime(data_agg, '%Y-%m'), i := round(coalesce(importo, 0)), r := round(rib, 2),
                            o := coalesce(offerenti, offerte), v := left(coalesce(vincitori, ''), 70),
                            g := left(coalesce(oggetto, ''), 90)) ORDER BY data_agg DESC)[1:6] ultime
    FROM esiti WHERE cat IS NOT NULL AND {chiave} IS NOT NULL GROUP BY {chiave}, cat HAVING count(*) >= 1"""
    return con.execute(q).fetchall()


print("== indici", flush=True)
ind = {"generato": str(date.today()), "fonte": "ANAC open data (CC BY-SA 4.0): cig, categorie-opera, aggiudicazioni, aggiudicatari",
       "anni": ANNI, "ente": {}, "provincia": {}}
for row in stats("cf"):
    cf, c, n, med, p25, p75, off, ult, ultime = row
    ind["ente"].setdefault(cf, {})[c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off, "ultime": ultime}
for row in stats("provincia"):
    pr, c, n, med, p25, p75, off, ult, ultime = row
    ind["provincia"].setdefault(pr, {})[c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off}
enti = {}
for cf, nome, prov in con.execute("SELECT cf, any_value(ente), any_value(provincia) FROM lavori WHERE cf IS NOT NULL GROUP BY cf").fetchall():
    enti[norm(nome)] = {"cf": cf, "prov": prov}
with gzip.open(f"{OUT}/ribassi.json.gz", "wt", encoding="utf-8") as f:
    json.dump(ind, f, ensure_ascii=False, separators=(",", ":"), default=str)
with gzip.open(f"{OUT}/enti.json.gz", "wt", encoding="utf-8") as f:
    json.dump(enti, f, ensure_ascii=False, separators=(",", ":"))
print(f"  enti con statistiche: {len(ind['ente'])} · province: {len(ind['provincia'])} · nomi enti: {len(enti)}")
print("  file:", {x: os.path.getsize(f'{OUT}/{x}') // 1024 for x in os.listdir(OUT)}, "KB")
print(f"== fatto in {time.time() - t0:.0f}s", flush=True)
