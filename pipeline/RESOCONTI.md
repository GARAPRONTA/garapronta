# Come scrivere i resoconti di gara (istruzioni per l'attività delle 6:40)

Input: `testi/AAAA/MM/GG/<CIG>/testi.json.gz` = lista di documenti {nome, tipo, formato, caratteri, testo},
già ordinati per importanza (disciplinare, lettera d'invito, bando, avviso, capitolato…).
Output: `resoconti/AAAA/MM/GG.json` = oggetto { "<CIG>": {titolo, lavori, punti[], attenzione[]} } (vedi 2026/11/20.json come esempio).

Campi:
- "titolo": titolo chiaro e COMPLETO in italiano normale (non maiuscolo), che dica cosa e dove: es. "Rifacimento della copertura della scuola primaria Rodari · Comune di Novara". Niente formule tipo "procedura aperta per l'affidamento dei lavori di". Non tagliare.
- "lavori": 2-3 frasi semplici su COSA si fa concretamente, presi da capitolato, relazione tecnica o computo: lavorazioni principali, dove (edificio/via/frazione), durata. Es. "Rimozione del vecchio manto in eternit, nuova copertura in pannelli coibentati e lattonerie. Lavori su edificio scolastico occupato: si lavora d'estate. Durata 120 giorni." Se i documenti non lo dicono, ometti il campo. Scrivilo SEMPRE quando c'è capitolato, relazione tecnica, computo o elenco prezzi.
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
