# GaraPronta — regole e vincoli (sempre validi)

## Sicurezza
- **Password e chiavi:** "Non mandarmi mai password o chiavi". Le chiavi (BREVO_API_KEY, VPS_PASSWORD, ecc.) le inserisce Pierfranco come segreti GitHub. Claude non le chiede, non le scrive, non le ripete. Una password incollata in chat in passato non va mai usata né ripetuta.
- **Login:** Claude non inserisce password per autenticarsi.
- **Protezioni anti-bot:** mai aggirarle (MEPA, Traspare, CAPTCHA). Il 28/11 Pierfranco ha chiesto di cambiare questa regola: non si può, è un limite di Claude in ogni chat. Si sistemano invece i lettori e si chiede l'accesso alle piattaforme. Niente flag per nascondere l'automazione, come --disable-blink-features=AutomationControlled.
- **TLS:** mai disattivare la verifica (niente `curl -k`).
- **Workflow:** niente workflow che eseguono script arbitrari passati come input; solo script fissi nel repository.

## Crediti Claude
- I resoconti automatici (attività programmate) restano SPENTI finché il servizio non è affinato e non ci sono iscritti: decisione di Pierfranco del 28/11. Non riaccenderli senza il suo ok.

## Email e clienti
- LIVE=0: le email vanno solo agli indirizzi +test finché non ci sono dominio e partita IVA. Prima di passare a LIVE=1 serve l'ok di Pierfranco.
- Niente email a freddo e niente marketing non richiesto.
- Le email non partono di notte: il blocco va dalle 14 alle 5.

## Contenuti
- **Nomi delle imprese:** compaiono ovunque, anche le ditte individuali (decisione di Pierfranco: "sono pur sempre pubbliche"). Rimozione su richiesta tramite pipeline/rimozioni.txt. L'informativa privacy lo spiega.
- **Resoconti di gara:**
  - solo fatti presenti nei documenti, ogni punto con la fonte;
  - "Non indicato nei documenti" quando manca qualcosa;
  - mai importi, date o requisiti inventati;
  - l'unico calcolo ammesso è la quota delle lavorazioni sul computo e l'arrotondamento delle quantità.
- **Ribassi e margini:** sono dati di mercato e stime, non consigli d'offerta.
- **Dati ANAC:** attribuzione CC BY-SA 4.0 in ogni email.

## Come lavorare con Pierfranco
- Parlare semplice, in italiano. Poca teoria, risultati concreti, numeri veri.
- Ragionare da capo azienda e "da miniera d'oro": ambizione, ma con i conti.
- Prima di costruire una cosa grossa, studiare le fonti e portare i numeri.
- Quando dice "vai", "fai tutto" o "perfetto", si esegue senza fare altre domande.
- Avvisare quando una cosa importante è pronta, senza raccontare ogni passaggio.
- Le cose che costano tempo a Pierfranco vanno ridotte al minimo: lui fa solo account e video.
