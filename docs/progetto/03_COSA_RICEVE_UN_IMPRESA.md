# GaraPronta — cosa riceve un'impresa

## Iscrizione (index.html)
- Si scelgono fino a 3 regioni oppure tutta Italia, tutte le categorie OG e OS (con "Mostra tutte") e una classifica SOA per ogni categoria.
- Si escludono le gare oltre la propria classifica, con un margine del 20%.

  | Classifica | Limite |
  |---|---|
  | I | 258.000 € |
  | II | 516.000 € |
  | III | 1.033.000 € |
  | III-bis | 1.500.000 € |
  | IV | 2.582.000 € |
  | IV-bis | 3.500.000 € |
  | V | 5.165.000 € |
  | VI | 10.329.000 € |
  | VII | 15.494.000 € |
  | VIII | illimitata |

- Se le regioni dell'impresa hanno meno di 5 occasioni nel giorno, si aggiungono le regioni confinanti, segnate "Regione vicina".

## L'email del mattino, sezione per sezione
1. **I tuoi enti:** cosa hanno fatto ieri gli enti che l'impresa segue (affidamenti, inviti, bandi, elenchi, esiti). Gli enti seguiti sono quelli scelti con un clic più i primi 15 della mappa, meno quelli tolti.
2. **Inviti e bandi**, ognuno con:
   - badge: "Puoi partecipare", "Ti serve un partner", "Supera la tua classifica", "Regione vicina", "🤝 Partner possibili", "📊 Computo";
   - **Cosa si fa:** 3-4 righe sul lavoro vero, cioè problema e luogo esatto, fasi e tecniche, quantità dal computo, condizioni di cantiere e durata;
   - **Lavorazioni principali** raggruppate per tipo, con la percentuale sull'importo. Le scrive il resoconto; se manca, si prendono dalle voci più pesanti del computo;
   - **Ribasso che vince in gare simili:** mediana dello stesso tipo di lavori e fascia d'importo. Si cerca nello stesso ente, poi provincia, regione e Italia, con almeno 6 gare;
   - **Quanto ti resta:** margine stimato e ribasso di pareggio;
   - link **"Leggi la descrizione completa"** alla scheda web.
3. **Elenchi operatori** aperti.
4. **Cercano proprio te:** gare dove la categoria dell'impresa è secondaria e quella prevalente non è sua.
5. **Chi ha vinto ieri:** esiti con ribasso e nome dell'impresa (anche ditte individuali).
6. **Enti da conoscere**, il lunedì o con MAPPA=1: chi affida i lavori dell'impresa senza bando, con link alla mappa web.
7. **Lavori senza gara:** affidamenti diretti della zona.
8. **A chi sono andati i lavori.**
9. **Piè di pagina:** attribuzione dei dati ANAC (CC BY-SA 4.0) e link alla privacy.

## La scheda web di ogni gara (g/CIG.html)
- Pulsante "Avviso ufficiale ANAC" (pubblicitalegale.anticorruzione.it/bandi/ID), sempre funzionante. Avviso rosso se il link dell'ente non porta alla gara.
- Cosa si fa, lavorazioni principali con le barre, "In breve" con la fonte di ogni punto.
- **Quanto si ribassa per vincere:** gare simili e "Quanto ti resta".
- **Analisi del computo metrico:**
  - voci e totale;
  - prezzario usato e anno; confronto con il prezzario in vigore (per esempio "−3,3% rispetto al 2026");
  - peso delle prime 3 voci;
  - prezzi da vecchie edizioni;
  - nuovi prezzi da controllare (NP), confrontati con voci simili del prezzario.
- **Trova partner:** imprese con SOA valida nella categoria mancante, vicino all'ente.

## Regole di calcolo
- I prezzi dei prezzari includono 15% di spese generali e 10% di utile, quindi RICARICO = 1,15 × 1,10 = 1,265.
- Margine = (1 − ribasso) × (1 + differenza tra prezzi del progetto e prezzario attuale) × 1,265 − 1.
- Il ribasso di pareggio è circa il 20,9% quando i prezzi del progetto sono quelli del prezzario in vigore.
- Chiave delle gare simili: `{E|P|R|I}|chiave|categoria|fascia|criterio`.
  - Fasce: f1 sotto 150.000 €, f2 sotto 1 milione, f3 sotto 5,382 milioni, f4 sopra.
  - Criterio: prezzo o OEPV.
- Categoria prevalente: prima la OG, poi le altre. Le categorie PVL arrivano senza ordine.

## Altre pagine pubbliche
- prezzi.html: ricerca gratuita nei prezzari regionali. Mostra il prezzo e il costo vivo stimato (prezzo / 1,265).
- Mappe degli enti per impresa, generate da scrivi_mappe().

## Esempio reale: Teramo (CIG BDEB9D9F6E, OS21, 161.470 €)
- **Cosa si fa:** messa in sicurezza della parete rocciosa lungo la SP 37 tra Castelli e Arsita.
  - Disgaggio su circa 540 m².
  - Circa 640 m di chiodature con barre GEWI Ø32 lunghe 5 m.
  - Rete a doppia torsione con funi su circa 590 m².
  - Muretto di sottoscarpa in c.a. e pietra, circa 25 m.
  - Durata 120 giorni.
- **Lavorazioni:** chiodature e tiranti 45%, rete e funi 29%, muretto 14%, pulizia e disgaggio 10%, trasporti 2%.
- **Computo:** 33 voci per 158.964 €, prezzario Abruzzo 2025, prezzi del 3,3% sotto il 2026, prime 3 voci pari al 62%.
- **Ribasso:** 6 gare OS21 tra 150.000 € e 1 milione della stessa Provincia di Teramo.
