# GaraPronta — architettura tecnica

## Dove sta tutto
- **Repository:** GitHub GARAPRONTA/garapronta, ramo main. Contiene codice, dati quotidiani, resoconti e sito.
- **Sito:** GitHub Pages, https://garapronta.github.io/garapronta/. Pagine: index.html (iscrizione), privacy.html, segui.html (conferma "segui ente"), prezzi.html (ricerca nei prezzari), g/CIG.html (una scheda per gara, non indicizzata), mappe degli enti.
- **Server italiano:** VPS Aruba, 3,99 € al mese. Serve perché ANAC open data e molte piattaforme degli enti bloccano gli IP esteri di GitHub. Accesso via sshpass dalle GitHub Actions con i segreti VPS_HOST e VPS_PASSWORD. Sopra gira DuckDB.
- **Email:** Brevo, lista 5, mittente garapronta@gmail.com. Il piano gratuito arriva a 300 email al giorno.
- **Segreti GitHub** (li inserisce solo Pierfranco): BREVO_API_KEY, VPS_HOST, VPS_PASSWORD, APIFY_TOKEN (Apify ormai spento, credito finito).

## Il giro di ogni giorno (ora italiana)
| Ora | Chi | Cosa |
|---|---|---|
| 21:47 | GitHub, giornaliera.yml | Scarica dalla PVL ANAC gli avvisi del giorno stesso (data/AAAA/MM/GG.json.gz) |
| subito dopo | GitHub, documenti.yml (parte dopo giornaliera) | Scarica e legge i documenti di tutte le gare di lavori; se una piattaforma blocca, riprova dal VPS; scrive testi/AAAA/MM/GG/ e il file giro_sera |
| 23:13 | Attività programmata Claude "resoconti della sera" | Scrive resoconti/AAAA/MM/GG.json; sopra le 8 gare divide il lavoro tra più agenti |
| 06:07 | GitHub, giornaliera.yml | Scarica gli avvisi completi di ieri |
| subito dopo | documenti.yml | Legge solo le gare nuove o fallite la sera; scrive il file giro_mattina |
| 07:03 | Attività programmata Claude "resoconti del mattino" | Aggiunge solo i CIG mancanti e scrive sempre resoconti/AAAA/MM/GG.mattino |
| al push dei resoconti | GitHub, invio.yml | Pubblica le schede web e manda le email; poi scrive il segnaposto inviati/AAAA-MM-GG |
| 08:37 | invio.yml | Invio di riserva, se i resoconti non sono arrivati |

- **Orari GitHub:** i cron di GitHub sono in UTC e partono spesso con circa un'ora di ritardo.
- **Invio notturno bloccato:** un push dei resoconti tra le 14 e le 5 non manda email.
- **Giorno di riferimento:** senza DATA, dalle 18 in poi gli script lavorano sul giorno stesso, prima delle 18 su ieri (funzione giorno_default).
- **Attività programmate Claude:**
  - trig_01NqxgsczGu2Xzy5KuKJH3Vp, "resoconti di gara del mattino", 07:03;
  - trig_01DM35CdNeEATTmABxzPgkU3, "resoconti di gara della sera", 23:13.

  Entrambe seguono pipeline/RESOCONTI.md.

## Altri workflow GitHub
- **banca.yml:** ogni 3 del mese. Sul VPS scarica gli open data ANAC e ricostruisce gli indici: ribassi.json.gz, enti.json.gz, mappa_enti.json.gz, partner.json.gz. Usa tools/banca_vps.py.
- **prezzari.yml:** passi cerca, scarica, indice, ispeziona, web. Costruisce l'indice dei prezzari regionali e le pagine prezzi.
- **storico.yml:** storico di 12 mesi per le statistiche regionali.
- **vps-setup.yml:** installa sul VPS p7zip-full, DuckDB e il resto.
- **vps-prova.yml, vps-diagnosi.yml:** diagnosi con script fissi (tools/vps_diagnosi.py). Non si accettano script arbitrari come input.
- **vps-anac.yml, ricerca-fonti.yml, brevo-check.yml:** utilità.
- **apify-deploy.yml:** non più usato.
- Tutti fanno `git pull -q --rebase -X theirs` prima del push.

## File principali
- **pipeline/garapronta.py:** il cuore. MODE = dati / schede / invio / tutto. Variabili: DATA (gg/mm/aaaa), LIVE=1 per inviare a tutti, DRY=1 per non inviare. Funzioni:
  - profilo dell'impresa: leggi_soa() legge "OG8-III, OS21", regioni_di(), per_iscritto() fa il filtro per impresa;
  - email: email_html(), pagina_gara() per le schede g/CIG.html;
  - ribassi e margine: storico() per i ribassi su gare simili, resta()/margine()/ribasso_pareggio();
  - computo: analisi_computo(), lavorazioni() e nome_voce();
  - partner ed enti: partner_per(), seguiti(), movimenti_enti(), sezione_enti(), pagina_mappa();
  - nomi: pubblico(), che esclude chi è in rimozioni.txt.
- **pipeline/documenti.py:** il lettore dei documenti.
  - Piattaforme e lettori: lettori.py, con Intercent e START Toscana via browser.
  - Archivi: apre zip, 7z e rar annidati, MAX_FILE 100 MB, MAX_ARCH 300 MB.
  - Link cloud: Nextcloud, Dropbox e Google Drive, con scarico fino a 250 MB.
  - Testo e salvataggio: senza_doppi() per i doppioni; spazio di testo per tipo (MAX_TESTO 900.000; disciplinare e bando interi, relazione e capitolato con quota riservata); salva computo.json.gz a parte.
  - Giri: giro sul VPS per le gare fallite; SOLO_CIG per riprovare singole gare.
- **pipeline/computo.py:** legge i computi metrici in stile PriMus (voci, quantità, prezzi), trova il prezzario usato, confronta con il prezzario in vigore (norm_cod per i codici con zeri diversi tra edizioni) e controlla i nuovi prezzi con prezzi simili (Jaccard ≥ 0,45, stessa unità).
- **pipeline/RESOCONTI.md:** regole per i resoconti scritti da Claude. Campi titolo, lavori ("Cosa si fa", 3-4 righe), lavorazioni [{cosa, quota}], punti con fonte, attenzione.
- **pipeline/rimozioni.txt:** imprese che hanno chiesto di non comparire.
- **tools/:**
  - banca_vps.py, enti_web.py (piattaforme ed elenchi per ente);
  - prezzari_cerca/scarica/indice/ispeziona/web.py, prezzi_web.py;
  - statistiche.py, fonti.py, vps_diagnosi.py, anac_vps.sh.

## Cartelle di dati nel repository
- data/AAAA/MM/GG.json.gz: avvisi PVL del giorno.
- testi/AAAA/MM/GG/: rapporto.json (esito per gara), CIG/testi.json.gz, CIG/computo.json.gz, giro_sera, giro_mattina.
- resoconti/AAAA/MM/GG.json e .mattino.
- inviati/AAAA-MM-GG: segna l'invio già fatto.
- indici/: ribassi, enti, mappa, partner, enti_web, prezzari.
- g/: schede web delle gare; g/prezzi/: prezzari per la pagina pubblica.

## Iscritti
- Contatti Brevo, lista 5. Attributi:
  - SOA: per esempio "OG 8-III, OS 21";
  - REGIONE: fino a 3, per esempio "Abruzzo, Lazio", oppure tutta Italia;
  - SETTORE;
  - ENTI ed ENTI_NO: enti seguiti ed esclusi.
- "Segui" e "smetti" funzionano con link tracciati: i clic si leggono da /smtp/statistics/events?event=clicks.
