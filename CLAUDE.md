# SafePath-Checker

Tooling per validare (e in seguito correggere) i nomi di file e directory di un albero documentale sincronizzato tra sistemi eterogenei (macOS / Windows / Linux, via SMB / NFS / NextCloud).

Stato attuale: **solo documentazione**. Non esiste ancora un'implementazione corrente nella root del progetto — l'unico codice presente è la versione storica in `OLD/` (vedi sotto).

---

## Struttura del progetto

```text
docs/          documentazione di sviluppo — fonte normativa
OLD/           versioni precedenti di script e documenti — NON considerare
TestData/      dati reali di test (nomi non conformi presi dal campo)
```

### `docs/` — documentazione di riferimento

| File | Ruolo |
| --- | --- |
| `docs/File naming Tech-rules.md` | **Normativo.** Regole di naming: charset Profilo B, regole posizionali, nomi riservati, limiti di lunghezza, case/Unicode, codici errore, test vectors, esempi di rewrite. È il documento a cui riferirsi per implementare la validazione. |
| `docs/Development guidelines.md` | **Normativo.** Istruzioni e linee guida implementative: architettura (`walker` / `rules` / `planner`), contratto di determinismo, gestione Unicode, path handling, hazard di rename, modello plan/apply, parità cross-implementazione, exit code. È il documento a cui riferirsi per implementare i tool. |
| `docs/File naming guide.md` | **Secondario.** Versione "umana"/discorsiva dello standard, usata dall'utente per documentare il tool verso i clienti. Consultarla solo come reference aggiuntiva; in caso di disaccordo vincono i due documenti sopra. |

### `OLD/` — materiale storico

Contiene versioni superate di script e documenti:

```text
OLD/safepath_checker.py      implementazione Python precedente
OLD/CLAUDE.md                CLAUDE.md precedente
OLD/FileNaming-Technical.md  specifica tecnica precedente
OLD/OLD-FileNaming.md        linee guida naming precedenti per i clienti
OLD/TestData-Report.csv      report generato dalla vecchia scansione
```

**Non considerare `OLD/` nel lavoro corrente**, né come reference né come base di codice, salvo richiesta esplicita nel prompt. Le regole e le scelte architetturali in `OLD/` divergono da quelle in `docs/`.

### `TestData/` — dati di test

Alberi di directory reali (documenti di cantiere/amministrativi) con nomi tipicamente non conformi: spazi doppi, apostrofi, `^`, `+`, `°`, punti interni, maiuscole, estensioni in maiuscolo, `.DS_Store`. Servono a validare il comportamento dei tool su dati veri.

**Regole d'uso obbligatorie:**

- **Tool di validazione / sola lettura** (`check`, report, scansioni): usare direttamente il path sorgente `TestData/`.
- **Tool che applicano modifiche** (`apply`, rename, qualsiasi scrittura): copiare prima `TestData/` in una directory temporanea e lavorare sulla copia. I dati originali vanno preservati.

Directory temporanea da usare per le copie e per qualsiasi file di lavoro: lo scratchpad di sessione, non `/tmp` e non la root del progetto.

```bash
cp -R "TestData" "$SCRATCHPAD/TestData"
```

---

## Regole e architettura: leggere i documenti, non riassunti

Questo file **non contiene** né deve contenere una sintesi delle regole di naming o dell'architettura dei tool. I documenti in `docs/` sono l'unica fonte, e cambiano.

Prima di implementare, modificare o discutere validazione, rename, limiti, codici errore, architettura o comportamento dei comandi: **leggere il documento di dettaglio pertinente**, per intero o nella sezione interessata.

- Regole di naming → `docs/File naming Tech-rules.md`
- Architettura e implementazione dei tool → `docs/Development guidelines.md`

Non lavorare a memoria, né su valori riportati altrove (incluso questo file, i commenti nel codice o `OLD/`): se un valore o una regola serve, va riletto dal documento. In caso di conflitto tra qualunque altra fonte e i documenti in `docs/`, vincono i documenti.

---

## Convenzioni

- Codice e identificatori in inglese; messaggi utente e report in italiano.
- Commenti solo sul *perché*, non sul *cosa*.
- I test vectors presenti nei documenti in `docs/` sono la suite di regressione minima.
