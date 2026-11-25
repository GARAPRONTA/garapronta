#!/bin/bash
# Sul server italiano: scarica i dataset ANAC (bloccati per gli IP esteri) ed esplora i campi.
set -u
D=/opt/garapronta/anac; mkdir -p $D; cd $D
B=https://dati.anticorruzione.it/opendata
echo "== catalogo"
curl -s -m 60 "$B/api/3/action/package_list" | head -c 4000; echo
for f in aggiudicazioni/filesystem/aggiudicazioni_csv.zip aggiudicatari/filesystem/aggiudicatari_csv.zip cig-2026/filesystem/cig_csv_2026_09.zip; do
  n=$(basename $f)
  echo "== $n"
  curl -fsL -m 900 --retry 3 -o $n "$B/download/dataset/$f" || { echo "ERRORE download"; continue; }
  ls -la $n
  for c in $(unzip -Z1 $n | head -3); do
    echo "-- $c"
    unzip -p $n "$c" | head -3 | cut -c1-2500
    echo "righe: $(unzip -p $n "$c" | wc -l)"
  done
done
df -h / | tail -1
