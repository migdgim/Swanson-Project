# Regole di ottimizzazione token

> Applicare sempre, salvo istruzione esplicita contraria.

---

## Modello

- Usa **Sonnet** per default (sviluppo, modifiche, debug, documentazione)
- Usa **Opus** solo per la prima esplorazione di un codebase mai visto prima — oppure se impostato esplicitsamente dall'utente

---

## Avvio sessione

- Leggi `ActualStatus.md` + `MANIFEST.md` (se presente) prima di qualsiasi altra cosa
- Non esplorare file di codice finché non hai capito il contesto dai file `.md`

---

## Lettura file

- Mai leggere un file intero se serve solo una funzione o una classe — chiedi la ricerca per nome
- Per file grandi: cerca prima con grep il blocco esatto, poi leggi solo quello
- Mai aprire: `*.log`, `*.json` di configurazione, `*.csv` — filtra con `tail`, `grep`, `jq`, `head`
- Mai aprire: `package-lock.json`, `pubspec.lock`, `*.lock` — inutili nel contesto
- Ignora sempre: `tests/`, `migrations/`, `node_modules/`, `venv/`, `build/`, `.dart_tool/`

---

## Modifiche ai file

- Per file di codice esistenti: modifica **solo la porzione pertinente** — mai riscrivere il file intero
- Per operazioni non-codice (copia, sostituzione testo, append, conteggio righe): usa **bash** invece di leggere e riscrivere

```bash
cp sorgente dest              # invece di Read + Write
sed -i '' 's/old/new/g' file  # invece di Read + Edit + Write  (macOS: -i '')
echo "riga" >> file           # invece di Read + riscrivi tutto
wc -l file                    # invece di leggere per contare
```

---

## Ricerche

- Specifica sempre tipo di file e directory: *"cerca solo in `src/` nei file `.py`"*
- Non fare mai ricerche globali senza filtro su tutto il progetto

---

## Comandi bash

- Usa sempre flag silenziosi dove disponibili: `-q`, `--quiet`, `-s`
- Limita sempre l'output: `| head -30`, `| tail -50`, `tree -L 2`
- Non riportare nel messaggio l'output di un comando salvo esplicita richiesta

---

## Output e risposte

- Dopo ogni modifica: **una riga** di conferma (es. `"Aggiunto campo email in models/user.py"`)
- Non spiegare le modifiche salvo richiesta esplicita
- Commenta il codice solo se necessario
- Non proporre alternative a meno che non ritieni che siano vantaggiose in modo significativo
- Non fare refactoring fuori dallo scope del task corrente a meno che non dovessi accorti di un bug. Avvisami prima.
- Non chiedere conferme intermedie su task chiari e scoped

---

## Gestione sessione

- Raggruppa modifiche correlate in **un solo messaggio** con i file target espliciti
- Aggiungi sempre vincoli negativi: *"non toccare X"*, *"ignora Y"*, *"solo in questo file"*
- Usa `/compact` per comprimere lo storico in sessioni lunghe senza ricominciare
- **A fine sessione:** aggiorna `ActualStatus.md` con le modifiche apportate in relazione agli sprint sviluppati e a quello ancora da iniziare. Deve esserci coerenza con `Sprint.md`.