# supabase/ — layer di pubblicazione

Postgres (Supabase) è la **verità dei dati pubblicati e curati** — non il motore di calcolo, che resta NetworkX in-memory nel motore Python.

## Stato

Il progetto Supabase **non è ancora creato**: l'organizzazione `migdgim@gmail.com` ha raggiunto il limite di **2 progetti free** (occupati da `guestrace` e `firetrace`). Il provisioning è **rinviato a S4** (fase di pubblicazione), quando si deciderà se fare l'upgrade a Pro o riorganizzare gli slot. Dettaglio in [`../ActualStatus.md`](../ActualStatus.md).

## Cosa conterrà

Solo dati derivati su **identificatori aperti** (MeSH, NCBI Gene, tassonomia, PMID): entità, archi con provenienza, ranking dei B per run, metriche di validazione, ipotesi curate. **Nessuna riga grezza SemMedDB/UMLS** (vincoli di licenza): SemMedDB resta un arricchimento *interno*, se ne pubblicano solo i risultati derivati. Schema completo in [`../DesignArchitecture.md`](../DesignArchitecture.md).

## Migrazioni

Applicate via **MCP Supabase** a partire da S4. La cronologia SQL sarà versionata in `migrations/`.
