# safepath — implementazione Go

Validazione e correzione dei nomi di file e directory secondo il Profilo B.

Le regole e l'architettura non sono documentate qui: le fonti normative sono
`docs/File naming Tech-rules.md` (regole) e `docs/Development guidelines.md`
(architettura). In caso di conflitto vincono i documenti.

## Build

```bash
CGO_ENABLED=0 go build -o safepath ./cmd/safepath
```

Binario statico, senza dipendenze a runtime. Cross-compilazione da un solo host:

```bash
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o safepath.exe ./cmd/safepath
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -o safepath     ./cmd/safepath
```

### Build legacy per Windows 7 / Server 2008 R2

Go 1.20 e' l'ultima release che supporta Windows 7 e Server 2008 R2. Il codice non usa API successive, quindi lo stesso sorgente si compila con il toolchain 1.20 usando un modfile alternativo (`go120.mod` / `go120.sum`) con versioni di `golang.org/x/*` ancora compatibili. Il `go.mod` principale resta invariato.

```bash
go install golang.org/dl/go1.20.14@latest && go1.20.14 download
GOTOOLCHAIN=local GOFLAGS=-modfile=go120.mod go1.20.14 test ./...
GOTOOLCHAIN=local GOFLAGS=-modfile=go120.mod CGO_ENABLED=0 GOOS=windows GOARCH=amd64 \
  go1.20.14 build -trimpath -o safepath-win2008r2.exe ./cmd/safepath
```

Con Go 1.20 `x/text` usa le tabelle Unicode 13.0.0 invece di 15.0.0, mentre l'header del report continua a dichiarare `UnicodeVersion` 15.0.0. I caratteri del Profilo B (fino a U+017F) sono stabili fra le due versioni e qualsiasi carattere fuori range e' comunque `CHR-001`; test vectors e output di `scan` / `auto-rename` su `TestData/` risultano identici alla build corrente (a parte il timestamp).

La versione si inietta al build:

```bash
go build -ldflags "-X github.com/EdoFede/safepath-checker/go/internal/cli.Version=1.0.0" ./cmd/safepath
```

## Uso

```bash
safepath scan        <path>...   # sola lettura: e' il dry run
safepath auto-rename <path>...   # rinomina mentre discende
```

Non esiste un `--dry-run`: `scan` lo e' per costruzione.

```bash
safepath scan "10 Amministrazione" --output-csv report.csv --output-json report.json
safepath scan . --exclude '*.tmp' --exclude-regex '\.(bak|old)$' --show-excluded
safepath auto-rename "20 Tecnico"
```

Exit code: `0` nulla da correggere, `1` violazioni, `2` argomenti non validi,
`3` errore di I/O, `4` deriva rilevata durante l'esecuzione.

## Struttura

```
cmd/safepath          entry point
internal/rules        validazione, nessun accesso al filesystem
internal/walker       traversal, tutta la divergenza fra OS
internal/planner      calcolo dei nomi di destinazione
internal/rename       esecuzione delle rinomine, journal, recupero
internal/report       console, CSV, JSON, manifest
internal/cli          parsing degli argomenti e orchestrazione
```

`rules` e `planner` non toccano il filesystem: i test li alimentano con valori
sintetici, e l'identita' dei risultati fra piattaforme e' una proprieta' del
design piu' che del flusso di lavoro.

## Mappa di traslitterazione

`internal/planner/charmap.go` e' pensato per essere editato. Un carattere fuori
Profilo B assente dalla mappa non viene indovinato: l'entry diventa
`action = manual` e il carattere compare nel riepilogo di fine esecuzione, che
e' il punto da cui partire per estendere la mappa. Aggiungere una riga e'
sufficiente, non c'e' altra logica da toccare.

## Test

```bash
go test ./...
```

I vettori normativi stanno in `shared/testvectors.json`, condiviso con
l'implementazione Python: nessuna implementazione ne tiene una copia propria.

## Trasporto delle rinomine

Oggi esiste il solo backend filesystem (`rename.FSRenamer`). Su alberi gestiti
da NextCloud il rename diretto scavalca il database e i client vedono
delete + create, perdendo share, versioni, commenti e tag: e' accettabile solo
per alberi non ancora condivisi, ed e' bene eseguirlo con la sincronizzazione in
pausa. L'interfaccia `rename.Renamer` isola il trasporto, cosi' che un backend
WebDAV `MOVE` possa essere aggiunto senza toccare walker, rules o planner.
