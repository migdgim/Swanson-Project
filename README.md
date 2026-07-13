# Swanson Project

Motore di **Literature-Based Discovery (LBD)** per la letteratura biomedica.
Estrae entità e relazioni da PubMed, costruisce un grafo di conoscenza e genera **ipotesi di collegamenti non ovvi** secondo il **modello ABC di Swanson**: se A e C non compaiono mai insieme in letteratura ma condividono un termine intermedio B, allora A–C è un'ipotesi da investigare.

**Dominio pilota:** disbiosi intestinale / microbioma (A) ↔ tumorigenesi e immunità antitumorale (C). L'architettura è espandibile ad altri corridoi A→C.

Progetto di ricerca **non commerciale**, pensato per il **pubblico dominio**: dati aperti e interfaccia web consultabile dai ricercatori.

## Perché è diverso

Il valore non è *generare* connessioni — un grafo di co-occorrenze ne produce migliaia, quasi tutte spurie — ma **filtrarle**. Il sistema si giudica con un test di validazione temporale (*time-slicing*): costruisce il grafo solo con la letteratura fino a una certa data e verifica se "predice" scoperte diventate note solo dopo. Se non batte un semplice baseline a frequenza, il sistema non funziona — e lo dichiara.

## Struttura

| Cartella | Contenuto |
|---|---|
| `engine/` | Motore Python: `ingest`, `graph`, `discovery`, `validation`, `export`, `publish` |
| `web/` | Interfaccia web pubblica (Next.js) — *in arrivo (S5)* |
| `supabase/` | Schema e migrazioni del layer di pubblicazione |
| `Project.md` | Brief completo: obiettivo, test di successo, vincoli |
| `DesignArchitecture.md` | Architettura tecnica |
| `Sprint.md` / `ActualStatus.md` | Piano di lavoro e stato corrente |

## Stato

In sviluppo — fase di fondazione. Vedi [`ActualStatus.md`](ActualStatus.md).

## Licenza

Da definire (orientamento: open source / open data).
