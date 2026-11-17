# Development Environment Setup — Go

Come predisporre l'ambiente di sviluppo e test per l'implementazione **Go** dei tool di SafePath-Checker, su **macOS** (versioni recenti, Apple Silicon) e su **Windows 10/11**.

Il documento copre solo l'ambiente. Le regole di naming e l'architettura dei tool sono in `docs/File naming Tech-rules.md` e `docs/Naming tools Dev notes.md`, che restano l'unica fonte normativa.

---

## 1. Cosa serve e perché

| Componente | Versione | Perché |
| --- | --- | --- |
| Go toolchain | 1.26.x (ultima stabile: 1.26.5) | linguaggio; `go.mod` pinna anche la toolchain |
| Git | ≥ 2.40 | versionamento, origin su GitHub |
| `golang.org/x/text` | pinnato in `go.mod` | normalizzazione Unicode e case folding — vedi §3.1 delle Dev notes |
| golangci-lint | v2.12.2 | lint; installazione da binario, non `go install` |
| gotestsum *(opzionale)* | ultima | output test leggibile e JUnit XML per la CI |
| Editor | VS Code + estensione Go, o GoLand | — |

Due vincoli del progetto influenzano direttamente il setup:

- **Determinismo cross-platform.** Lo stesso codice deve produrre output byte-identico su macOS, Windows e Linux (Dev notes §2). L'ambiente deve quindi essere riproducibile: versione di Go pinnata, dipendenze pinnate, niente tool installati "a caso" con versioni diverse tra macchine.
- **La versione delle tabelle Unicode è parte del contratto.** `x/text` non è una dipendenza qualsiasi: la sua versione determina il risultato di case folding e lookup di categoria, e finisce nell'header del report. Non aggiornarla senza rigenerare i test vector.

---

## 2. macOS (Apple Silicon)

### 2.1 Prerequisiti

Homebrew, già disponibile. Verifica:

```bash
brew --version
git --version          # se manca: xcode-select --install
uname -m               # deve restituire arm64
```

### 2.2 Installazione di Go

```bash
brew install go
go version              # go version go1.26.5 darwin/arm64
```

In alternativa, se serve una versione specifica non allineata a quella di brew, usa il pkg ufficiale da <https://go.dev/dl/> (`go1.26.5.darwin-arm64.pkg`), che installa in `/usr/local/go`.

**Nota su Gatekeeper**: il pkg ufficiale è firmato e notarizzato da Google, non dà problemi. Il tema Gatekeeper si ripresenterà invece sui *nostri* binari distribuiti ai clienti (Dev notes §8) — è un problema di distribuzione, non di sviluppo.

### 2.3 PATH e variabili d'ambiente

Homebrew mette `go` già nel PATH. Va aggiunto invece `GOPATH/bin`, dove finiscono i tool installati con `go install`. In `~/.zshrc`:

```bash
export GOPATH="$HOME/go"
export PATH="$PATH:$GOPATH/bin"
```

Poi `source ~/.zshrc` e verifica:

```bash
go env GOPATH GOBIN GOMODCACHE
```

### 2.4 Tooling

```bash
# linter — installazione da binario, come raccomandato dal progetto upstream
curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/HEAD/install.sh \
  | sh -s -- -b "$(go env GOPATH)/bin" v2.12.2
golangci-lint --version

# runner dei test (opzionale ma comodo)
go install gotest.tools/gotestsum@latest
```

`go vet`, `gofmt` e il language server (`gopls`, installato automaticamente da VS Code) arrivano con la toolchain o con l'editor.

### 2.5 Filesystem: attenzione al case-insensitive

APFS è, di default, **case-insensitive**. Questo è un problema concreto per questo progetto: le regole `UNQ-001` (collisioni casefold) e i test di rename case-only (Dev notes §5.1) non sono verificabili in modo affidabile su un volume case-insensitive — la creazione delle fixture fallisce o si sovrascrive silenziosamente.

Verifica il volume corrente:

```bash
diskutil info / | grep -i "case-sensitive"
```

Se serve un volume case-sensitive per i test, creane uno APFS dedicato nello stesso container (non richiede ripartizionamento né perdita di dati):

```bash
diskutil apfs addVolume disk3 "Case-sensitive APFS" GoTests
# il device del container si ricava da: diskutil list
```

Il volume compare in `/Volumes/GoTests`. In alternativa, un'immagine disco sparse:

```bash
hdiutil create -size 2g -fs "Case-sensitive APFS" -volname GoTests ~/GoTests.sparseimage
hdiutil attach ~/GoTests.sparseimage
```

I test che dipendono dalla case-sensitivity vanno scritti in modo da **rilevare** il comportamento del filesystem e fare skip esplicito quando non è supportato, non da assumerlo. Questo è necessario comunque, perché la stessa suite gira su NTFS in CI.

---

## 3. Windows 10 / 11

### 3.1 Installazione con winget

Da PowerShell:

```powershell
winget install --id GoLang.Go
winget install --id Git.Git
winget install --id GolangCI.golangci-lint
```

Chiudi e riapri il terminale (winget aggiorna il PATH solo per le nuove sessioni), poi:

```powershell
go version              # go version go1.26.5 windows/amd64
git --version
golangci-lint --version
```

Se `winget` non è disponibile, usa l'MSI ufficiale `go1.26.5.windows-amd64.msi` da <https://go.dev/dl/>.

### 3.2 PATH

L'MSI installa Go in `C:\Program Files\Go` e aggiunge `go` al PATH. Va aggiunto a mano `%USERPROFILE%\go\bin`:

```powershell
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\go\bin",
  "User")
```

### 3.3 Long paths — obbligatorio

Il walker deve poter attraversare alberi pre-remediation che superano `MAX_PATH` (Dev notes §4.2). Go applica il prefisso `\\?\` automaticamente per i path assoluti, ma **git e gli strumenti di supporto no**: senza questa impostazione il checkout delle fixture lunghe fallisce.

Da PowerShell **come amministratore**:

```powershell
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name LongPathsEnabled -Value 1 -Type DWord
```

E per git:

```powershell
git config --global core.longpaths true
```

Riavvia la sessione. Il comportamento long-path va comunque verificato esplicitamente nella suite di test: è la sorgente più comune di divergenza tra le implementazioni su Windows.

### 3.4 Line endings — obbligatorio

Il progetto scrive output con `\n` e legge `testvectors.json` byte per byte (Dev notes §2). Se git converte i line ending in checkout, i test di parità falliscono su Windows e non altrove.

```powershell
git config --global core.autocrlf false
```

Da affiancare a un `.gitattributes` nel repo (§5.2) che rende la scelta indipendente dalla configurazione della singola macchina.

### 3.5 Antivirus

Windows Defender scansiona ogni binario prodotto da `go build` e ogni file creato dai test. Su una suite che crea molti file temporanei l'impatto è misurabile. Se accettabile secondo le policy locali, escludi le directory di lavoro:

```powershell
Add-MpPreference -ExclusionPath "$env:USERPROFILE\go"
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\go-build"
```

### 3.6 Terminale

Usa Windows Terminal con PowerShell 7+. Verifica che la code page sia UTF-8, altrimenti i nomi accentati nei report appaiono corrotti (problema di visualizzazione, non di correttezza):

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

Per renderlo permanente, aggiungilo al profilo PowerShell (`$PROFILE`).

---

## 4. Clone del repository

**SSH** (consigliato se hai già una chiave su GitHub):

```bash
git clone git@github.com:EdoFede/SafePath-Checker.git
cd SafePath-Checker
```

**HTTPS** (se non hai chiavi configurate):

```bash
git clone https://github.com/EdoFede/SafePath-Checker.git
cd SafePath-Checker
```

Setup della chiave SSH, se serve:

```bash
ssh-keygen -t ed25519 -C "edofede@gmail.com"
# macOS
pbcopy < ~/.ssh/id_ed25519.pub
# Windows PowerShell
Get-Content ~\.ssh\id_ed25519.pub | Set-Clipboard
```

Poi incolla la chiave in GitHub → Settings → SSH and GPG keys, e verifica con `ssh -T git@github.com`.

Identità git, se non già configurata globalmente:

```bash
git config user.name "Edoardo Federici"
git config user.email "edofede@gmail.com"
```

---

## 5. Layout e bootstrap del repository

Il repository non contiene ancora codice: allo stato attuale è solo documentazione. Questa sezione descrive la struttura delle directory e il bootstrap del modulo, da eseguire una volta sola.

### 5.1 Layout del repository

Le due implementazioni vivono in due alberi separati, con una terza directory per ciò che condividono:

```text
go/                        modulo Go — go.mod alla sua radice
  cmd/<nome-binario>/      main, parsing CLI, exit code
  internal/walker/         traversal, codice OS-specific
  internal/rules/          validazione, nessun accesso al filesystem
  internal/planner/        risoluzione dei rename

python/                    package Python — pyproject.toml alla sua radice
  src/<nome-package>/
    walker.py
    rules.py
    planner.py
  tests/

shared/                    fonte unica, nessun codice eseguibile
  testvectors.json         vettori di test (Tech-rules §8)
  ruleset.json             costanti di Tech-rules §1
  schema/report.schema.json

docs/
TestData/
```

Radici separate perché Go vuole `go.mod` alla radice del proprio albero — e vi ancora la semantica di `internal/` — mentre Python vuole `pyproject.toml` alla radice del proprio. Con entrambi nella root del repository i due toolchain si sovrappongono e ogni strumento di packaging vede file che non gli competono.

`internal/` impedisce a livello di compilatore che i package vengano importati da fuori dal modulo: appropriato, dato che l'unica interfaccia pubblica è la CLI.

**`cmd/` non è di per sé un `package main`**: è un contenitore. Il `package main` sta in una directory sotto di esso, e il nome del binario prodotto è il nome di quella directory. Il nome del comando e dei sottocomandi non è ancora deciso — `<nome-binario>` è un segnaposto, da fissare sulle Dev notes prima di creare la directory.

**Le parti comuni sono dati, non codice.** Le regole di naming non possono essere una libreria condivisa: sarebbero comunque due implementazioni. Ciò che deve esistere in una sola copia sono le fixture e le costanti — Dev notes §7 è esplicito, *"a single `testvectors.json` in the repo, consumed by both test suites. Neither implementation carries its own copy"*, e nessuna delle due implementazioni è autoritativa sul comportamento. Per questo `shared/` sta al livello più alto e non dentro una delle due.

### 5.2 Inizializzazione del modulo Go

Da dentro `go/`:

```bash
go mod init github.com/EdoFede/SafePath-Checker/go
go get golang.org/x/text@latest
```

Il suffisso `/go` nel module path riflette la posizione nel repository ed è ciò che rende risolvibile l'import da parte di `go get`.

Dalla root del repository, i comandi Go accettano `-C`:

```bash
go -C go build ./...
```

### 5.3 Accesso a `shared/` dalle due implementazioni

Per Python non c'è attrito: è un path relativo letto a runtime.

Per Go sì. **`//go:embed` non può includere file fuori dalla directory del package** — un path che risale con `../` viene rifiutato in compilazione. Il rimedio dipende da chi legge il file:

| Consumatore | Approccio |
| --- | --- |
| Test (`testvectors.json`) | lettura a runtime, path risolto rispetto alla root del repository |
| Binario distribuito (`ruleset.json`) | copia sotto `go/internal/`, generata da `go generate` e verificata allineata in CI |

I symlink sarebbero una terza via, ma su Windows richiedono `core.symlinks true` e privilegi: da evitare in un repository destinato a essere clonato anche dai clienti.

### 5.4 `.gitattributes`

Necessario perché la parità byte-per-byte non dipenda dalla configurazione git della singola macchina:

```gitattributes
* text=auto eol=lf
shared/**  -text
*.json     -text
*.jsonl    -text
*.go       text eol=lf
*.py       text eol=lf
*.ps1      text eol=crlf
*.bat      text eol=crlf
```

L'intero contenuto di `shared/` e i file `.jsonl` sono marcati binari di proposito: sono confrontati byte per byte dai test di parità e non devono subire alcuna conversione.

### 5.5 `.gitignore`

Il `.gitignore` esistente copre Python, OS e IDE ma non Go. Vanno aggiunte le voci Go:

```gitignore
# Go
*.exe
*.exe~
*.test
*.out
/go/bin/
/go/vendor/
/dist/
```

Attenzione: le regole `build/` e `dist/` già presenti nella sezione Python coprono in parte, ma le directory sotto `go/` e i binari Windows no.

---

## 6. Verifica dell'ambiente

Comandi identici sulle due piattaforme, da eseguire **da dentro `go/`**:

```bash
go build ./...
go vet ./...
gofmt -l .              # nessun output = tutto formattato
go test ./...
golangci-lint run
```

Dalla root del repository, la stessa cosa con `-C`:

```bash
go -C go build ./...
go -C go test ./...
```

Con `gotestsum`:

```bash
gotestsum --format testname -- -race ./...
```

Il flag `-race` va usato solo se il walker verrà parallelizzato. Non è gratuito in termini di tempo, ma su codice concorrente è l'unico modo per intercettare data race prima che diventino non-determinismo in produzione.

### 6.1 Test su TestData

`TestData/` contiene nomi non conformi reali e sta nella root del repository: da `go/` il path risale di un livello. Le regole d'uso sono vincolanti:

- **Tool di sola lettura** (`check`, report): usare direttamente il path sorgente.

  ```bash
  go run ./cmd/<nome-binario> check ../TestData
  ```

- **Tool che scrivono** (`plan`/`apply`, rename): lavorare **sempre** su una copia in directory temporanea, mai sull'originale.

  ```bash
  cp -R ../TestData "$SCRATCHPAD/TestData"
  go run ./cmd/<nome-binario> apply "$SCRATCHPAD/TestData" --apply
  ```

  Su Windows:

  ```powershell
  Copy-Item -Recurse ..\TestData "$env:TEMP\TestData"
  ```

Ricorda che `--apply` è opt-in: il default è dry-run (Dev notes §6.3).

### 6.2 Exit code

Utile in fase di verifica: `check` restituisce **1** quando trova violazioni, e questo non è un errore. Non confonderlo con un crash quando scripti il tool o configuri la CI.

```bash
go run ./cmd/<nome-binario> check ../TestData; echo "exit: $?"
```

La tabella completa dei codici è nelle Dev notes §9.

---

## 7. Cross-compilazione

Un singolo host di build produce i binari per tutte le piattaforme. `CGO_ENABLED=0` è obbligatorio: rende il binario completamente statico, senza dipendenza da glibc/musl (Dev notes §8).

Da dentro `go/`, con gli artefatti raccolti in `dist/` alla root del repository.

macOS / Linux:

```bash
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o ../dist/<nome>-windows-amd64.exe ./cmd/<nome-binario>
CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -o ../dist/<nome>-macos-arm64       ./cmd/<nome-binario>
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -o ../dist/<nome>-linux-amd64       ./cmd/<nome-binario>
```

`GOOS=darwin` è il valore richiesto dalla toolchain; `macos` nel nome del file è solo una scelta di leggibilità per l'artefatto distribuito.

Windows PowerShell:

```powershell
$env:CGO_ENABLED=0; $env:GOOS="darwin"; $env:GOARCH="arm64"
go build -o ../dist/<nome>-macos-arm64 ./cmd/<nome-binario>
```

Per build riproducibili, elimina i path assoluti dal binario:

```bash
go build -trimpath -ldflags="-s -w" ./cmd/<nome-binario>
```

---

## 8. Configurazione dell'editor

### VS Code

Estensione **Go** (`golang.go`). `.vscode/` è in `.gitignore`, quindi la configurazione resta locale:

```json
{
  "go.useLanguageServer": true,
  "go.lintTool": "golangci-lint",
  "go.lintFlags": ["--fast"],
  "go.formatTool": "gofmt",
  "editor.formatOnSave": true,
  "files.eol": "\n",
  "files.encoding": "utf8",
  "gopls": {
    "ui.semanticTokens": true
  }
}
```

`files.eol: "\n"` è rilevante su Windows: evita che l'editor introduca CRLF nei file di test o nelle fixture.

---

## 9. Riepilogo delle differenze tra piattaforme

| Aspetto | macOS | Windows |
| --- | --- | --- |
| Installazione | `brew install go` | `winget install GoLang.Go` |
| Case-sensitivity FS | APFS case-**in**sensitive di default; serve volume dedicato per alcuni test | NTFS case-insensitive; stesso limite |
| Long paths | `PATH_MAX` 1024 byte, non modificabile | `LongPathsEnabled=1` + `core.longpaths true` |
| Line endings | nessuna azione | `core.autocrlf false` + `.gitattributes` |
| Antivirus | — | escludere le directory di build |
| Encoding terminale | UTF-8 di default | code page da impostare a UTF-8 |

---

## 10. Problemi ricorrenti

| Sintomo | Causa | Rimedio |
| --- | --- | --- |
| `go: command not found` dopo l'installazione | PATH non ricaricato | nuova sessione di terminale |
| `golangci-lint` non trovato dopo `go install` | `GOPATH/bin` fuori dal PATH | §2.3 / §3.2 |
| Test di parità falliscono solo su Windows | CRLF introdotti da git | §3.4 e `.gitattributes` |
| Fixture con path lunghi non si estraggono | long paths disattivati | §3.3 |
| Test su collisioni case-only falliscono su macOS | volume case-insensitive | §2.5, o skip esplicito nel test |
| Nomi accentati corrotti nel report a terminale | code page non UTF-8 | §3.6 — visualizzazione, non correttezza |
| Output diverso tra due macchine | versione di `x/text` diversa | `go.mod` deve pinnare la versione; confronta `unicode_version` nell'header del report |
