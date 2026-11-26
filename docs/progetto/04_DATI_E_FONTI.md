# GaraPronta — dati e fonti

## Fonti in uso
| Fonte | Cosa dà | Come si prende |
|---|---|---|
| ANAC Piattaforma Pubblicità Legale (PVL), API | Avvisi del giorno: bandi, inviti, indagini, affidamenti diretti, esiti, elenchi, preinformazioni, rettifiche | Da GitHub, ogni giorno |
| ANAC open data, licenza CC BY-SA 4.0 | cig 2023-2025 mensili, aggiudicazioni (4,86 milioni di righe), aggiudicatari (5,4 milioni), categorie-opera (12,2 milioni), attestazioni-soa-v2, stazioni-appaltanti | Solo dal VPS italiano (gli IP esteri sono bloccati), ogni 3 del mese |
| Piattaforme degli enti | Bando, disciplinare, allegati, progetto | documenti.py da GitHub, poi dal VPS per le gare fallite |
| Prezzari regionali | Prezzi delle voci per l'analisi del computo | prezzari.yml; formati Excel, CSV, ODS, XML SIX, XML EASY |

Dataset ANAC disponibili ma non ancora usati: partecipanti, lavorazioni, quadro-economico, OCDS.

## Prezzari indicizzati
- 12 regioni indicizzate.
- Anno forzato dove serve: Sicilia 2024, Lazio 2023, Umbria 2025.
- Il formato XML EASY è comune a Campania, Piemonte, Sardegna e Toscana.
- Si tiene un prezzario solo se ha almeno 1.000 voci.
- Mancano: Toscana e Veneto (esportazioni dentro le web app), Trento (elencoprezzi2026.provincia.tn.it), Valle d'Aosta (formato Excel da sistemare), e quelli solo in PDF (Bolzano, Molise, Liguria, Basilicata, Calabria).

## Indici costruiti sul VPS (cartella indici/)
- **ribassi.json.gz:** mediane dei ribassi per ente, provincia, regione, Italia e "simili" (21.646 chiavi).
- **enti.json.gz e mappa_enti.json.gz:** chi affida cosa, quanto spesso, a quante imprese.
- **partner.json.gz:** 35.447 imprese con SOA valida (stato PUBBLICO).
- **enti_web.json.gz:** piattaforma ed elenchi di ogni ente.

## I numeri del mercato (12 mesi, novembre 2025 - ottobre 2026)
- 1.057.681 avvisi sulla PVL.
- Lavori affidati senza gara: 120.622, circa 4,8 miliardi €, valore tipico 23.484 €.
- Servizi e forniture affidati senza gara: 521.031 servizi e 248.369 forniture.
- Bandi di lavori: 5.986. Indagini di mercato: 17.510, di cui 3.787 di lavori.
- Imprese diverse che hanno lavorato con la PA: 259.622. Enti che hanno pubblicato: 23.043.
- Ribasso tipico che vince nei lavori: 14,7% (OG1 13,0%, OG3 14,6%, OG8 19,2%).
- Picco a dicembre: 18.976 lavori affidati.
- Il 24/11/2026: 4.708 affidamenti diretti, di cui 685 di lavori.
- Ogni giorno escono circa 26-40 gare di lavori, tra bandi e indagini.

## Concorrenti
- InfoAppalti, da 250 € l'anno.
- SIGAP, 0,79 € al giorno.
- Infobandi, da 38 a 100 € al mese.
- AppaltoChiaro, concorrente diretto.

## Fonti trovate per "gare prima che escano" (da studiare)
- **Programmi triennali dei lavori:** obbligatori per lavori da 150.000 € in su (art. 37 del D.Lgs. 36/2023, allegato I.5).
  - Ogni intervento ha un CUI; la scheda D è il programma, la scheda E l'elenco annuale (lavori da avviare entro l'anno).
  - Dove si pubblicano: portale nazionale MIT Servizio Contratti Pubblici, https://www.serviziocontrattipubblici.it/it/consultazione/programmazione-triennale-lavori-beni-e-servizi/. Esiste un tracciato tecnico dei dati ("tracciati_programmi"), ma nessun open data dichiarato.
  - 10 regioni pubblicano su un portale proprio: Basilicata, Bolzano, Emilia-Romagna, Friuli-Venezia Giulia, Liguria, Lombardia, Marche, Toscana, Trento, Valle d'Aosta.
- **Collegamento con le gare:** il CUI del programma compare nei CIG ANAC. Quindi programmato meno già bandito dà i lavori in arrivo.
- **Preinformazioni:** avvisi PVL "AVVISI_DI_PRE-INFORMAZIONE", circa 23 in 5 giorni, già nei nostri dati.
- **Da valutare:** OpenCUP (progetti finanziati prima della gara) e Puglia open data (CSV della programmazione).

## Licenza
I dati ANAC sono CC BY-SA 4.0: va sempre citata la fonte. Se un giorno ridistribuiamo i dati grezzi, vanno con la stessa licenza.
