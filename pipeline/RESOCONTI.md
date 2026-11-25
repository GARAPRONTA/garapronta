# Come scrivere i resoconti di gara (istruzioni per l'attività delle 6:40)

Input: `testi/AAAA/MM/GG/<CIG>/testi.json.gz` = lista di documenti {nome, tipo, formato, caratteri, testo},
già ordinati per importanza (disciplinare, lettera d'invito, bando, avviso, capitolato…).
Il lettore gira due volte: la sera (circa 23:15, sulle gare del giorno) e la mattina (circa 7:10, solo le gare arrivate dopo).
Se il file del giorno esiste già, AGGIUNGI solo i CIG che mancano e non toccare quelli già scritti.
Output: `resoconti/AAAA/MM/GG.json` = oggetto { "<CIG>": {titolo, lavori, punti[], attenzione[]} } (vedi 2026/11/20.json come esempio).

Campi:
- "titolo": titolo chiaro e COMPLETO in italiano normale (non maiuscolo), che dica cosa e dove: es. "Rifacimento della copertura della scuola primaria Rodari · Comune di Novara". Niente formule tipo "procedura aperta per l'affidamento dei lavori di". Non tagliare.
- "lavori": la DESCRIZIONE DELL'INTERVENTO, 3-4 righe (60-100 parole), precisa e concreta, come la spiegherebbe il direttore tecnico
  dell'impresa al capocantiere. Non ripetere l'oggetto della gara: spiega il lavoro vero. Ricavala leggendo relazione tecnica e illustrativa,
  capitolato e computo metrico (computo.json.gz). Deve dire, quando i documenti lo riportano:
  1) il problema da risolvere e dove esattamente (strada e km, edificio e piano, frazione, lunghezza del tratto);
  2) come si fa: le fasi in ordine e le tecniche (es. disgaggio, perforazioni, getto, demolizione, posa), con i materiali principali;
  3) le quantità che contano, prese dal computo (m², m, m³, n. pezzi, kg) — arrotondate;
  4) condizioni di cantiere che pesano sul prezzo (strada aperta al traffico, lavori in quota o su fune, edificio occupato, accessi difficili) e la durata.
  Esempio di forma (dati di fantasia, non copiarli): "Rifacimento della copertura della palestra della scuola media di via Roma, con
  infiltrazioni diffuse. Si rimuove il vecchio manto in lamiera con bonifica dell'eternit sottostante (circa 900 m²), si posano pannelli
  sandwich coibentati da 10 cm e nuove lattonerie, con linea vita in copertura. Ponteggio su tre lati e scuola aperta: lavori nei
  mesi estivi. Durata 90 giorni."
  Solo fatti dai documenti, nessuna cifra inventata. Se non ci sono capitolato, relazione o computo, usa bando/disciplinare e scrivi meno.
- "lavorazioni": elenco di 3-6 lavorazioni principali, RAGGRUPPATE PER TIPO di lavoro, con il peso sull'importo dei lavori:
  [{"cosa": "Consolidamento parete rocciosa con tiranti e barre", "quota": 44}, {"cosa": "Rete metallica di rivestimento", "quota": 18}, ...].
  Fonte: testi/AAAA/MM/GG/<CIG>/computo.json.gz (lista di documenti {nome, tipo, testo}; usa quello con tipo "computo", non il computo dei costi della sicurezza).
  Somma gli importi delle voci dello stesso tipo (es. tutte le voci di scavo insieme, tutti gli infissi insieme) e dividi per il totale dei lavori; quote intere, in ordine decrescente.
  Nomi brevi (max 6 parole) e concreti, come li direbbe un capocantiere: "Cappotto termico", "Infissi in PVC", "Impianto fotovoltaico", "Scavi e rinterri", "Asfaltatura".
  Escludi oneri e costi della sicurezza. Se c'è solo capitolato o relazione e nessun importo, metti le lavorazioni senza "quota". Se non ci sono informazioni, ometti il campo.

Regole:
- Solo fatti scritti nei documenti. Se un'informazione non c'è, scrivi "Non indicato nei documenti". Mai inventare.
- Ogni punto ha "fonte" breve: documento + paragrafo/punto (es. "Disciplinare §14.4", "Bando IV.2", "Lettera d'invito art. 5").
- Punti, in quest'ordine quando presenti (max 9): Importo · Requisiti (SOA categoria e classifica, avvalimento) ·
  Subappalto · Sopralluogo (obbligatorio? fino a quando? come prenotarlo) · Garanzia (importo, riduzioni) ·
  Criterio (prezzo più basso / OEPV con punteggi tecnica-prezzo) · Punti facili (criteri tabellari che si prendono solo dichiarando) ·
  Chiarimenti (scadenza) · Offerta (scadenza, apertura). Per le indagini di mercato: Requisiti · Come candidarsi · Scadenza · N. imprese invitate.
- "attenzione": max 3 frasi brevi sulle cose che fanno escludere o che sorprendono.
- Testo in italiano semplice, frasi brevi, importi in euro arrotondati.
- Gare con esito diverso da "ok" in rapporto.json o senza testo utile: salta (non scrivere nulla).
