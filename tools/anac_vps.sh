#!/bin/bash
# Sul server italiano: scarica i dataset ANAC (bloccati per gli IP esteri) ed esplora i campi.
set -u
D=/opt/garapronta/anac; mkdir -p $D; cd $D
B=https://dati.anticorruzione.it/opendata
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
echo "== elenco dataset (pagine HTML del catalogo)"
for p in 1 2 3 4; do curl -s -m 60 -A "$UA" "$B/dataset?page=$p" | grep -o 'href="/opendata/dataset/[a-z0-9-]*"' | sed 's/.*dataset\///;s/"//'; done | sort -u | tr '\n' ' '; echo
echo "== risorse di alcuni dataset"
for ds in categorie-opera cig-2026 cig-2025 stazioni-appaltanti attestazioni-soa-v2-filesystem-attestato-csv partecipanti lavorazioni; do
  echo "-- $ds"; curl -s -m 60 -A "$UA" "$B/dataset/$ds" | grep -o 'https://dati.anticorruzione.it/opendata/download/[^"]*' | sort -u | head -8
done
prova() {  # $1 = percorso dopo /download/dataset/
  n=$(basename "$1"); echo "== $n"
  [ -s "$n" ] || curl -fsL -m 1200 --retry 2 -A "$UA" -o "$n" "$B/download/dataset/$1" || { echo "ERRORE download"; rm -f "$n"; return; }
  ls -la "$n"
  if [[ $n == *.zip ]]; then c=$(unzip -Z1 "$n" | head -1); unzip -p "$n" "$c" | head -3 | cut -c1-2000; echo "righe: $(unzip -p "$n" "$c" | wc -l)"
  else head -3 "$n" | cut -c1-2000; echo "righe: $(wc -l < "$n")"; fi
}
prova categorie-opera/filesystem/categorie-opera_csv.zip
prova cig-2025/filesystem/cig_csv_2025_10.zip
prova attestazioni-soa-v2/filesystem/categorie_rilasciate_CKAN.csv
prova attestazioni-soa-v2/filesystem/attestato_CKAN.csv
prova stazioni-appaltanti/filesystem/stazioni-appaltanti_csv.zip
df -h / | tail -1
