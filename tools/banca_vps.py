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
att = scarica("attestazioni-soa-v2/filesystem/attestato_CKAN.csv", forza=True)
att_cat = scarica("attestazioni-soa-v2/filesystem/categorie_rilasciate_CKAN.csv", forza=True)
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
       any_value(oggetto_lotto) oggetto, any_value(replace(sezione_regionale, 'SEZIONE REGIONALE ', '')) regione
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
CREATE OR REPLACE TABLE vinc_righe AS
SELECT id_aggiudicazione id, codice_fiscale cf_imp, denominazione
FROM read_csv('{aggi}', {OPZ}) WHERE id_aggiudicazione IN (SELECT id FROM agg)""")
con.execute("""CREATE OR REPLACE TABLE vinc AS
SELECT id, string_agg(DISTINCT denominazione, ' + ') vincitori, min(cf_imp) cf_imp FROM vinc_righe GROUP BY id""")

# Gare con concorrenza vera (no affidamenti diretti), ribasso plausibile
con.execute("""
CREATE OR REPLACE TABLE esiti AS
SELECT l.cig, l.cf, l.ente, l.provincia, l.regione, c.cat, l.importo, l.procedura, l.oggetto, a.rib, a.offerte, a.offerenti,
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
       "anni": ANNI, "ente": {}, "provincia": {}, "regione": {}, "italia": {}}
for row in stats("cf"):
    cf, c, n, med, p25, p75, off, ult, ultime = row
    ind["ente"].setdefault(cf, {})[c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off, "ultime": ultime}
for row in stats("provincia"):
    pr, c, n, med, p25, p75, off, ult, ultime = row
    ind["provincia"].setdefault(pr, {})[c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off}
for row in stats("regione"):
    rg, c, n, med, p25, p75, off, ult, ultime = row
    ind["regione"].setdefault(rg, {})[c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off}
for row in stats("'IT'"):
    _, c, n, med, p25, p75, off, ult, ultime = row
    ind["italia"][c] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off}
# ---- mappa degli enti bersaglio: chi affida lavori senza gara o con inviti, per regione e categoria
con.execute("""
CREATE OR REPLACE TABLE target AS
WITH t AS (
  SELECT l.cf, l.ente, l.provincia, l.regione, c.cat, l.importo, l.procedura, a.data_agg, l.data_pub, v.cf_imp,
         CASE WHEN l.procedura ILIKE '%AFFIDAMENTO DIRETTO%' THEN 'diretto'
              WHEN l.procedura ILIKE '%NEGOZIATA%' THEN 'negoziata' ELSE 'altro' END tipo
  FROM lavori l JOIN cat c USING (cig) LEFT JOIN agg a USING (cig) LEFT JOIN vinc v ON v.id = a.id
  WHERE l.cf IS NOT NULL AND c.cat IS NOT NULL)
SELECT regione, cat, cf, any_value(ente) ente, any_value(provincia) prov,
       count(*) FILTER (WHERE tipo = 'diretto') diretti, count(*) FILTER (WHERE tipo = 'negoziata') negoziate,
       count(*) totale, round(sum(importo) FILTER (WHERE tipo IN ('diretto', 'negoziata'))) valore,
       count(DISTINCT cf_imp) imprese, count(cf_imp) con_vincitore,
       mode(month(coalesce(data_pub, data_agg))) FILTER (WHERE tipo IN ('diretto', 'negoziata')) mese_picco
FROM t GROUP BY regione, cat, cf""")
con.execute("""CREATE OR REPLACE TABLE conc AS
SELECT cf, cat, max(n) top_n FROM (
  SELECT l.cf, c.cat, v.cf_imp, count(*) n FROM lavori l JOIN cat c USING (cig) JOIN agg a USING (cig) JOIN vinc v ON v.id = a.id
  WHERE v.cf_imp IS NOT NULL GROUP BY 1, 2, 3) GROUP BY 1, 2""")
mappa = {}
for rg, c, cf, ente, prov, dir_, neg, tot, val, imp, conv, mese, top in con.execute("""
  SELECT t.regione, t.cat, t.cf, t.ente, t.prov, t.diretti, t.negoziate, t.totale, t.valore, t.imprese, t.con_vincitore,
         t.mese_picco, k.top_n FROM target t LEFT JOIN conc k USING (cf, cat)
  WHERE t.diretti + t.negoziate >= 2 ORDER BY t.diretti + t.negoziate DESC""").fetchall():
    lst = mappa.setdefault(rg or "?", {}).setdefault(c, [])
    if len(lst) < 40:
        lst.append({"cf": cf, "ente": ente, "prov": prov, "dir": dir_, "neg": neg, "val": val, "imp": imp,
                    "conv": conv, "top": top, "mese": mese})
with gzip.open(f"{OUT}/mappa_enti.json.gz", "wt", encoding="utf-8") as f:
    json.dump({"generato": str(date.today()), "anni": ANNI, "regioni": mappa}, f, ensure_ascii=False, separators=(",", ":"), default=str)
print("  mappa enti: regioni", len(mappa), "· righe", sum(len(v) for r in mappa.values() for v in r.values()), flush=True)

# ---- trova partner: imprese con attestazione SOA valida, per provincia e categoria, con le gare vinte
OPZ2 = "delim=';', header=true, all_varchar=true, ignore_errors=true"
print("  stati attestazioni:", con.execute(f"SELECT ATA_attestato_stato, count(*) FROM read_csv('{att}', {OPZ2}) GROUP BY 1 ORDER BY 2 DESC").fetchall(), flush=True)
con.execute(f"""
CREATE OR REPLACE TABLE soa AS
SELECT a.ATA_impresa_codiceFiscale cf_imp, any_value(a.ATA_impresa_denominazione) nome, any_value(a.ATA_provincia_nome) prov,
       replace(c.ATCR_categoria, ' ', '') cat, max(c.ATCR_classifica) classe
FROM read_csv('{att}', {OPZ2}) a JOIN read_csv('{att_cat}', {OPZ2}) c ON c."_idAttestazione" = a."_idAttestazione"
WHERE a.ATA_attestato_stato = 'PUBBLICO'
  AND try_strptime(a.ATA_attestato_dataScadenzaValiditaQuinquennale, '%Y-%m-%d') >= current_date
GROUP BY 1, 4""")
con.execute("""CREATE OR REPLACE TABLE vittorie AS
SELECT v.cf_imp, count(*) n
FROM vinc_righe v JOIN agg a ON a.id = v.id GROUP BY 1""")
con.execute("""CREATE OR REPLACE TABLE vitt_cat AS
SELECT v.cf_imp, c.cat, count(*) n FROM vinc_righe v JOIN agg a ON a.id = v.id JOIN cat c ON c.cig = a.cig GROUP BY 1, 2""")
partner = {}
for prov, c, cf_imp, nome, classe, vt, vc in con.execute("""
  SELECT s.prov, s.cat, s.cf_imp, s.nome, s.classe, coalesce(t.n, 0), coalesce(k.n, 0)
  FROM soa s LEFT JOIN vittorie t USING (cf_imp) LEFT JOIN vitt_cat k ON k.cf_imp = s.cf_imp AND k.cat = s.cat
  WHERE s.prov IS NOT NULL
  QUALIFY row_number() OVER (PARTITION BY s.prov, s.cat ORDER BY coalesce(k.n, 0) DESC, coalesce(t.n, 0) DESC) <= 15""").fetchall():
    partner.setdefault(prov, {}).setdefault(c, []).append({"cf": cf_imp, "nome": nome, "cl": classe, "v": vt, "vc": vc})
with gzip.open(f"{OUT}/partner.json.gz", "wt", encoding="utf-8") as f:
    json.dump({"generato": str(date.today()), "fonte": "ANAC attestazioni SOA e aggiudicatari (CC BY-SA 4.0)", "province": partner},
              f, ensure_ascii=False, separators=(",", ":"))
print("  partner: province", len(partner), "· imprese SOA valide", con.execute("select count(distinct cf_imp) from soa").fetchone(), flush=True)

# ---- ribassi su gare simili: categoria + fascia d'importo + criterio, a diversi livelli di zona
print("  criteri:", con.execute("SELECT criterio, count(*) FROM esiti GROUP BY 1 ORDER BY 2 DESC LIMIT 8").fetchall(), flush=True)
con.execute("""CREATE OR REPLACE TABLE esiti2 AS SELECT *,
  CASE WHEN importo < 150000 THEN 'f1' WHEN importo < 1000000 THEN 'f2' WHEN importo < 5382000 THEN 'f3' ELSE 'f4' END fascia,
  CASE WHEN criterio ILIKE '%MINOR PREZZO%' OR criterio ILIKE '%PREZZO PI%BASSO%' THEN 'prezzo'
       WHEN criterio ILIKE '%VANTAGGIOSA%' THEN 'oepv' END crit
FROM esiti WHERE cat IS NOT NULL AND importo > 0""")
simili = {}
LIVELLI = [("E", "cf"), ("P", "provincia"), ("R", "regione"), ("I", "'IT'")]
for sig, col in LIVELLI:
    for extra in (", fascia, crit", ", fascia", ""):
        filtro = "AND crit IS NOT NULL" if "crit" in extra else ""
        q = f"""SELECT {col} k, cat{extra}, count(*) n, round(median(rib), 2), round(quantile_cont(rib, 0.25), 2),
                       round(quantile_cont(rib, 0.75), 2), round(avg(coalesce(offerenti, offerte)), 1),
                       list(struct_pack(d := strftime(data_agg, '%Y-%m'), i := round(coalesce(importo, 0)), r := round(rib, 2),
                            o := coalesce(offerenti, offerte), v := left(coalesce(vincitori, ''), 70), g := left(coalesce(oggetto, ''), 90))
                            ORDER BY data_agg DESC)[1:6]
                FROM esiti2 WHERE {col} IS NOT NULL {filtro} GROUP BY ALL HAVING count(*) >= 3"""
        for row in con.execute(q).fetchall():
            row = list(row)
            k, c = row[0], row[1]
            dims = row[2:2 + extra.count(",")]
            n, med, p25, p75, off, ult = row[2 + extra.count(","):]
            chiave = "|".join([sig, str(k), c] + [str(x) for x in dims])
            simili[chiave] = {"n": n, "med": med, "p25": p25, "p75": p75, "off": off,
                              **({"ultime": ult} if sig == "E" else {})}
ind["simili"] = simili
print("  chiavi gare simili:", len(simili), flush=True)

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
