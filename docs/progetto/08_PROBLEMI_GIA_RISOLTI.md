# GaraPronta — problemi già risolti (per non rifarli)

| Problema | Causa | Soluzione |
|---|---|---|
| ANAC open data non si scarica da GitHub | Blocca gli IP esteri | Tutto dal VPS italiano (banca.yml, tools/banca_vps.py) |
| Molte piattaforme degli enti rispondono 403 o vanno in timeout | IP esteri bloccati | Giro di riprova dal VPS per le gare fallite (vps_giro in documenti.py) |
| Apify a 0 crediti | Credito finito | Spento, sostituito dal VPS |
| Gli orari programmati di GitHub arrivano in ritardo di circa un'ora | Limite di GitHub | Dati anticipati; l'email parte al push dei resoconti; invio di riserva alle 8:37 |
| I resoconti della sera farebbero partire le email di notte | Il push di resoconti/ avvia invio.yml | invio.yml salta se il push arriva tra le 14 e le 5 |
| Computo di Teramo non trovato | Progetto su un Nextcloud linkato in un PDF; cloud lento dall'estero; ZIP da 189 MB dentro uno ZIP | Si seguono i link cloud (CONDIVISI, scarica_esterno); esito "progetto su cloud da scaricare dall'Italia" va al VPS; MAX_ARCH 300 MB |
| Relazione tecnica vuota nei testi | Il capitolato da 440.000 caratteri esauriva il budget di testo | Budget per tipo di documento (TETTO), MAX_TESTO 900.000; tipo "relazione" in testa; doppioni .p7m tolti |
| "Relazione geotecnica" presa per relazione tecnica | La regex trovava "tecnic" dentro "geotecnica" | Regex con la parola subito dopo "relazione" |
| Il computo tagliato | Limite MAX_TESTO | computo.json.gz salvato a testo intero, a parte |
| Codici del prezzario diversi tra le edizioni (zeri) | ABR25 contro ABR26 | norm_cod() in computo.py |
| Parser del computo | Primo carattere tagliato, numerazione "n / n", code di codice prese per numeri di voce | Regex INIZIO, ultimo_cod, finestra di 400 righe |
| Prezzari | UM "1 cad" in Lombardia, XML SIX ed EASY, caratteri XML non validi, codici Lazio, Excel Umbria senza estensione, dati sbagliati in Valle d'Aosta | Parser dedicati in prezzari_indice.py; dati della Valle d'Aosta scartati |
| Categoria prevalente sbagliata | Le categorie PVL arrivano senza ordine | Prima la OG (prevalente()) |
| Link dell'ente che non porta alla gara (Fossalto) | La gara non è pubblicata sulla piattaforma o il link porta alla home | Pulsante "Avviso ufficiale ANAC" più avviso rosso |
| Conflitti al push tra workflow | Più workflow scrivono nel repository | `git pull -q --rebase -X theirs` ovunque |
| Errori 500 delle API GitHub nel lancio dei workflow | GitHub | Riprovare con gh workflow run o con la REST dispatches |
| Classificatore di sicurezza che blocca | Flag anti-bot, input di script arbitrari, curl -k | Tolti: solo script fissi, mai TLS disattivato, mai evasione anti-bot |
| KeyError in _indici, import re mancante, ordine di RESOCONTI | Bug | Corretti |
| Numeri del parser come "5.78 kg" | Il punto delle migliaia italiano a volte è letto come decimale | DA SISTEMARE in computo.voci(): quantità con il punto delle migliaia |
