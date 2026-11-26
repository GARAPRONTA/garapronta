# GaraPronta — stato attuale

Aggiornato al 26 novembre 2026.

## In una frase
Il servizio gira da solo ogni giorno e manda un'email completa di gare, analisi e dati. Non incassa ancora: mancano dominio, partita IVA e account social, tutte cose che deve fare Pierfranco.

## Cos'è GaraPronta
- Avvisi automatici su gare d'appalto e affidamenti pubblici per le imprese edili italiane.
- Un solo marchio per tutti i settori degli appalti. Oggi è attivo solo "Lavori edili"; gli altri 7 settori (verde, pulizie, ecc.) verranno dopo.
- Nome scelto il 23/11/2026, dopo aver scartato "BandoGiusto" (dominio già preso). Concorrente diretto noto: AppaltoChiaro.
- Sito: https://garapronta.github.io/garapronta/ in stile "Liquid Glass" iPhone, accento blu.
- Account del servizio: Gmail garapronta@gmail.com, GitHub "GARAPRONTA", Brevo (email), server Aruba (VPS).
- Documento di riferimento: "GaraPronta — punto della situazione e piano per la miniera d'oro", https://claude.ai/artifact/XA6fnWtaSYLYhsXmrtB8Sy

## Come è andata l'ultima mattina (26/11, gare del 25/11)
- 33 gare di lavori trovate.
- 15 documenti letti; 11 senza file; 4 bloccate (403); 2 in timeout; 1 con scansioni.
- 15 resoconti scritti, tutti con la descrizione "Cosa si fa" in 3-4 righe e 14 con le lavorazioni.
- Email inviate alle 07:11.

## Cosa funziona oggi (dettagli nei file 02 e 03)
- Lettura quotidiana di tutte le gare di lavori d'Italia (circa 26-40 al giorno), con documenti, computo, resoconto e scheda web.
- Email personalizzata per regione, categorie e classifica SOA, con ribassi, margine, partner, enti da seguire, esiti e affidamenti diretti.
- Giro serale (21:47 e 23:13) più giro del mattino, attivo dal 26/11.
- Prova con 100 imprese finte: 100 email in 3 secondi. Il servizio regge 50-100 imprese senza modifiche.

## Cosa manca per incassare (tocca a Pierfranco)
- [ ] Comprare il dominio garapronta.it
- [ ] Account Instagram e TikTok @garapronta
- [ ] Account pubblicitario Meta
- [ ] Commercialista: partita IVA e controllo dell'informativa privacy
- [ ] Stripe, quando c'è la partita IVA
- Due email già scritte per chiedere l'accesso a Traspare e Consip (MEPA), non inviate: per ora si è scelto il solo link.

## Prossimo lavoro tecnico deciso
1. **"Gare prima che escano"** (leva 3 della visione). Proposta del 26/11; Pierfranco ha chiesto di fermarsi un attimo per preparare questa cartella. Il piano:
   - studiare le fonti: programmi triennali sul portale MIT Servizio Contratti Pubblici e su 10 portali regionali (Basilicata, Bolzano, Emilia-Romagna, Friuli-Venezia Giulia, Liguria, Lombardia, Marche, Toscana, Trento, Valle d'Aosta);
   - costruire una banca dei lavori programmati (CUI, descrizione, importo, anno, priorità, CUP);
   - togliere quelli già banditi, confrontando il CUI con i CIG ANAC;
   - mettere nell'email "Lavori in arrivo nella tua zona", il segnale sugli enti seguiti e le preinformazioni del giorno (già presenti nei dati PVL).

   Prima si studia e si portano i numeri (quante regioni e quanti lavori), poi si costruisce.
2. Prezzari mancanti: Toscana e Veneto (esportazioni dentro le loro web app), Trento, Valle d'Aosta, e quelli solo in PDF (Bolzano, Molise, Liguria, Basilicata, Calabria).
3. Usare il "quadro d'incidenza della manodopera" per la quota non ribassabile nel calcolo del margine.
4. Rapporto mensile per l'impresa: "sei iscritto a X enti su Y".
5. Fasi successive della visione: ufficio gare (bozze DGUE), commissioni sulle cauzioni, dati per i fornitori di materiali.

## Impresa di prova
- **Codimar Srl**: Abruzzo e Lazio; categorie OG3, OG8-III, OS21, OS12-B.
- In un anno ci sono 64 gare utili in Abruzzo e Lazio, 323 aggiungendo le regioni confinanti.
- Gare usate come esempi:
  - Teramo, CIG BDEB9D9F6E, OS21, 161.470 €;
  - Fossalto, CIG BDEA12F4F7, Unione dei Comuni Sorgenti del Biferno.
