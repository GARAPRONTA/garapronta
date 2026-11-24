# Come scrivere i resoconti di gara (istruzioni per l'attività delle 6:40)

Input: `testi/AAAA/MM/GG/<CIG>/testi.json.gz` = lista di documenti {nome, tipo, formato, caratteri, testo},
già ordinati per importanza (disciplinare, lettera d'invito, bando, avviso, capitolato…).
Output: `resoconti/AAAA/MM/GG.json` = oggetto { "<CIG>": {titolo, punti[], attenzione[]} } (vedi 2026/11/20.json come esempio).

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
