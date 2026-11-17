# safepath — implementazione Python

Validazione e correzione dei nomi di file e directory di un albero documentale
sincronizzato fra sistemi eterogenei.

```
safepath scan        <path>...    cammina e valida            -> report
safepath auto-rename <path>...    cammina, valida e rinomina  -> report + azioni
```

`scan` e' in sola lettura ed **e' il dry run** di `auto-rename`: non esiste un
`--dry-run`, che duplicherebbe `scan` invitando all'errore di presumere il
default opposto.

Le regole di naming sono normate in `docs/File naming Tech-rules.md`,
l'architettura in `docs/Development guidelines.md`. Questo README copre solo
l'uso e la struttura del package.

---

## Installazione

Richiede CPython 3.13 (la minor fa parte del contratto di comportamento).

```bash
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

`unicodedata2` e' pinnato a **15.0.0** e non va aggiornato senza rigenerare i
test vector: la coppia interprete + tabelle Unicode definisce il comportamento,
e la versione dichiarata finisce nell'header di ogni report. Quando
l'implementazione Go sara' validata, le due dovranno dichiarare la stessa
versione: due esecuzioni con tabelle diverse non sono confrontabili.

---

## Struttura

Il layout riflette la separazione interna dell'architettura: `rules` e `planner`
non accedono mai al filesystem, e tutta la divergenza fra sistemi operativi e'
confinata in `walker`.

```text
src/safepath/
  rules/      validazione, nessun accesso al filesystem  -> codici di violazione
  planner/    calcolo dei nomi di destinazione           -> operazioni
  walker/     traversal, esclusioni, codice OS-specific  -> entry
  rename/     esecuzione delle rinomine, journal         -> esiti
  report/     accumulazione e serializzazione            -> console / CSV / JSON
  cli/        parsing degli argomenti ed exit code
```

`charmap.py` e' pensato per essere editato: aggiungere una riga rende
automaticamente correggibile un carattere che oggi produce `action = manual`.
I caratteri incontrati e privi di sostituzione sono elencati in fondo a ogni
esecuzione.

---

## Opzioni

| Opzione | Effetto |
| --- | --- |
| `--show-ok` | include nel report anche le voci conformi |
| `--exclude <glob>` | esclude le voci che corrispondono al glob (ripetibile) |
| `--exclude-regex <re>` | esclude le voci che corrispondono alla regex (ripetibile) |
| `--show-excluded` | include nel report le voci escluse |
| `--output-csv <file>` | scrive il report in CSV (UTF-8 con BOM, CRLF) |
| `--output-json <file>` | scrive il report in JSON (UTF-8 senza BOM) |
| `--emit-manifest <file>` | scrive il manifest JSONL delle voci |
| `--journal <file>` | *(solo auto-rename)* registra le rinomine eseguite |

Le esclusioni sono **solo additive**: un'entry e' esclusa se corrisponde a un
qualsiasi pattern dell'uno o dell'altro insieme, e l'ordine degli argomenti non
cambia mai l'esito. Escludere una directory ne esclude l'intero sottoalbero, che
non viene proprio percorso.

## Exit code

| Codice | Significato |
| --- | --- |
| 0 | nulla da correggere |
| 1 | violazioni trovate (`scan`) o rimaste (`auto-rename`) |
| 2 | argomenti non validi o path inutilizzabile |
| 3 | errore di I/O nel walk o nella scrittura di un output |
| 4 | deriva: una directory e' cambiata durante l'esecuzione |

Le violazioni sono dati, non errori: exit 1 resta distinguibile da un crash
perche' il tool sia scriptabile. `auto-rename` che ha riparato tutto esce **0** —
la domanda utile per uno script non e' "c'era qualcosa che non andava?" ma "c'e'
ancora qualcosa?".

---

## Verifica

```bash
ruff check . && ruff format --check .
mypy src
pytest
```

I vettori normativi stanno in `shared/testvectors.json`, consumati anche dalla
suite Go: nessuna delle due implementazioni ne tiene una copia propria.

### Parita' con l'implementazione Go

> **Nota.** L'implementazione Go presente nel repository **non e' ancora stata
> validata**, e non va usata come riferimento di comportamento: la fonte
> normativa restano i documenti in `docs/` e `shared/testvectors.json`. Il
> confronto sotto e' utile a far emergere divergenze, ma quando le due
> implementazioni non concordano va riletto il documento, non allineata l'una
> all'altra.

Una volta validate entrambe, il controllo che conta non e' che i test Python
passino, ma che le due implementazioni producano lo stesso output. Dalla root
del repository:

```bash
go -C go build -o /tmp/safepath ./cmd/safepath
export NO_COLOR=1 COLUMNS=120

/tmp/safepath scan TestData --show-ok --output-json /tmp/go.json > /tmp/go.txt
python -m safepath scan TestData --show-ok --output-json /tmp/py.json > /tmp/py.txt

diff /tmp/go.txt /tmp/py.txt      # solo generated_at puo' differire
diff /tmp/go.json /tmp/py.json
```

Qualsiasi differenza oltre al timestamp e' un bug in una delle due.

### Test su TestData

`TestData/` contiene nomi non conformi reali e va trattato come sorgente:

- **sola lettura** (`scan`): usare direttamente il path sorgente;
- **scrittura** (`auto-rename`): lavorare **sempre** su una copia in directory
  temporanea, mai sull'originale.

```bash
cp -R ../TestData "$TMPDIR/TestData"
python -m safepath auto-rename "$TMPDIR/TestData"
```
