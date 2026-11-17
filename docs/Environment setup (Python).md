# Development Environment Setup — Python

Come predisporre l'ambiente di sviluppo e test per l'implementazione **Python** dei tool di SafePath-Checker, su **macOS** (versioni recenti, Apple Silicon) e su **Windows 10/11**.

Il documento copre solo l'ambiente. Le regole di naming e l'architettura dei tool sono in `docs/File naming Tech-rules.md` e `docs/Naming tools Dev notes.md`, che restano l'unica fonte normativa.

Per l'implementazione Go, vedi `docs/Development environment setup (Go).md`. Le sezioni comuni alle due implementazioni — layout del repository, `shared/`, `.gitattributes`, clone — sono ripetute qui in forma essenziale, ma il documento Go resta il riferimento per la parte Go.

---

## 1. Cosa serve e perché

| Componente | Versione | Perché |
| --- | --- | --- |
| CPython | 3.13.x, **minor pinnata** | interprete; la minor fa parte del contratto (Dev notes §8) |
| Git | ≥ 2.40 | versionamento, origin su GitHub |
| `unicodedata2` | pinnata in `requirements.txt` | tabelle Unicode disaccoppiate dall'interprete — Dev notes §3.1 |
| Ruff | ultima stabile | lint + format, sostituisce flake8/isort/black |
| mypy | ultima stabile | type checking |
| pytest | ultima stabile | test runner |
| pytest-cov *(opzionale)* | ultima | copertura |
| PyInstaller *(solo per distribuzione)* | ultima | binario self-contained per i clienti |
| Editor | VS Code + Python/Pylance, o PyCharm | — |

Tre vincoli del progetto influenzano direttamente il setup:

- **Determinismo cross-platform.** Lo stesso codice deve produrre output byte-identico su macOS, Windows e Linux, e identico a quello prodotto dall'implementazione Go (Dev notes §2, §7). L'ambiente deve essere riproducibile: versioni pinnate, nessun pacchetto installato globalmente "a mano".
- **`unicodedata2` non è una dipendenza qualsiasi.** Lo stdlib `unicodedata` è legato alla build di CPython: 3.11 e 3.13 spediscono tabelle diverse. `unicodedata2` è **l'unico modo** per allineare il comportamento a una build Go pinnata (Dev notes §3.1). Non usare `unicodedata` per category lookup e non aggiornare `unicodedata2` senza rigenerare i test vector.
- **La minor di CPython è parte del pin.** Dev notes §8: *"Pin the interpreter minor version alongside `unicodedata2`; the pair defines behaviour."* Non basta pinnare la libreria: la coppia interprete + tabelle definisce il comportamento.

---

## 2. macOS (Apple Silicon)

### 2.1 Prerequisiti

Homebrew, già disponibile. Verifica:

```bash
brew --version
git --version          # se manca: xcode-select --install
uname -m               # deve restituire arm64
```

**Non usare il Python di sistema** (`/usr/bin/python3`): è gestito da Apple, può cambiare minor con un aggiornamento di macOS e non è pinnabile. Questo è incompatibile con il vincolo di cui a §1.

### 2.2 Installazione dell'interprete

Due opzioni, entrambe valide. Scegline una e usala su tutte le macchine di sviluppo.

**Opzione A — Homebrew** (più semplice, una sola minor per volta):

```bash
brew install python@3.13
python3.13 --version    # Python 3.13.x
```

Il binario finisce in `/opt/homebrew/bin/python3.13`.

**Opzione B — pyenv** (consigliata se serve tenere più minor installate, o riprodurre esattamente una patch version):

```bash
brew install pyenv
```

In `~/.zshrc`:

```bash
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
```

Poi `source ~/.zshrc` e:

```bash
pyenv install 3.13.9
pyenv local 3.13.9      # da dentro il repository: crea .python-version
python --version
```

Il file `.python-version` va **versionato**: è il pin dell'interprete a cui fa riferimento §1.

### 2.3 Ambiente virtuale

Sempre un venv per progetto, mai installazioni globali con `pip`:

```bash
cd SafePath-Checker/python
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Verifica di essere nel venv giusto:

```bash
which python            # .../python/.venv/bin/python
python -c "import sys; print(sys.executable, sys.version)"
```

Per disattivare: `deactivate`.

### 2.4 Filesystem: attenzione al case-insensitive

APFS è, di default, **case-insensitive**. È un problema concreto per questo progetto: le regole sulle collisioni casefold e i test di rename case-only (Dev notes §5.1, §5.2) non sono verificabili in modo affidabile su un volume case-insensitive — la creazione delle fixture fallisce o si sovrascrive silenziosamente.

Verifica il volume corrente:

```bash
diskutil info / | grep -i "case-sensitive"
```

Se serve un volume case-sensitive per i test, creane uno APFS dedicato nello stesso container (non richiede ripartizionamento né perdita di dati):

```bash
diskutil list                      # individua il device del container
diskutil apfs addVolume disk3 "Case-sensitive APFS" PyTests
```

Il volume compare in `/Volumes/PyTests`. In alternativa, un'immagine disco sparse:

```bash
hdiutil create -size 2g -fs "Case-sensitive APFS" -volname PyTests ~/PyTests.sparseimage
hdiutil attach ~/PyTests.sparseimage
```

I test che dipendono dalla case-sensitivity vanno scritti in modo da **rilevare** il comportamento del filesystem e fare skip esplicito quando non è supportato, non da assumerlo — la stessa suite gira su NTFS in CI. Un modo pulito è una fixture pytest che crea due file con case diverso in `tmp_path` e fa `pytest.skip()` se ne vede uno solo.

### 2.5 Nomi non-UTF-8 nei test

Su macOS il kernel rifiuta i nomi non-UTF-8, quindi le fixture per `valid_utf8: false` (Dev notes §4.1) **non si possono creare su disco**: vanno iniettate come `Entry` sintetiche direttamente in `rules`, che per design non tocca il filesystem (Dev notes §1). Su Linux la creazione via `os.mkdir(b"...")` funziona; su macOS e Windows no.

---

## 3. Windows 10 / 11

### 3.1 Installazione con winget

Da PowerShell:

```powershell
winget install --id Python.Python.3.13
winget install --id Git.Git
```

Chiudi e riapri il terminale (winget aggiorna il PATH solo per le nuove sessioni), poi:

```powershell
py -3.13 --version      # Python 3.13.x
git --version
```

In alternativa, l'installer ufficiale da <https://www.python.org/downloads/windows/>. Durante l'installazione:

- spunta **"Add python.exe to PATH"**;
- spunta **"Disable path length limit"** alla fine dell'installazione — è il flag che rende l'interprete *manifest-aware* per i long path (§3.3);
- installa il **py launcher**, che permette `py -3.13` per selezionare la minor.

### 3.2 Ambiente virtuale

```powershell
cd SafePath-Checker\python
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Se PowerShell blocca lo script di attivazione:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Verifica:

```powershell
Get-Command python | Select-Object Source
python -c "import sys; print(sys.executable, sys.version)"
```

### 3.3 Long paths — obbligatorio

Il walker deve poter attraversare alberi pre-remediation che superano `MAX_PATH` (Dev notes §4.2). A differenza di Go, **Python non applica il prefisso `\\?\` automaticamente**: servono sia l'impostazione di sistema, sia un interprete manifest-aware, sia — dove serve — il prefisso esplicito nel codice.

Da PowerShell **come amministratore**:

```powershell
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name LongPathsEnabled -Value 1 -Type DWord
```

E per git:

```powershell
git config --global core.longpaths true
```

Riavvia la sessione e verifica che l'interprete lo onori davvero:

```powershell
python -c "import os; os.makedirs('X'*250 + '\\' + 'Y'*250); print('ok')"
```

Se fallisce con `FileNotFoundError` o `OSError [WinError 3]`, l'interprete non è manifest-aware: reinstalla con l'installer ufficiale e il flag "Disable path length limit", oppure prefissa esplicitamente i path (path assoluto, backslash, nessun `.` o `..`):

```python
p = "\\\\?\\" + os.path.abspath(path)
```

Il comportamento long-path va comunque verificato esplicitamente nella suite di test: Dev notes §4.2 lo indica come **la sorgente più comune di divergenza tra Go e Python su Windows**.

### 3.4 Line endings — obbligatorio

Il progetto scrive output con `\n` e legge `testvectors.json` byte per byte (Dev notes §2). Se git converte i line ending in checkout, i test di parità falliscono su Windows e non altrove.

```powershell
git config --global core.autocrlf false
```

Da affiancare al `.gitattributes` nel repo (§5.4), che rende la scelta indipendente dalla configurazione della singola macchina.

Nel codice, la controparte è aprire **sempre in binario** o forzare `newline=""` / `newline="\n"`: `open(p, "w")` su Windows traduce `\n` in `\r\n` di default e questo, da solo, rompe la parità byte-per-byte.

```python
with open(path, "w", encoding="utf-8", newline="\n") as f: ...
```

### 3.5 Encoding — obbligatorio

Su Windows l'encoding di default di `open()` non è UTF-8 ma la code page ANSI del sistema. Report e manifest devono essere UTF-8 senza BOM (Dev notes §2), quindi:

- passare **sempre** `encoding="utf-8"` esplicito, mai affidarsi al default;
- non usare `encoding="utf-8-sig"`, che introduce il BOM;
- in sviluppo, attivare l'UTF-8 mode per far emergere subito eventuali dimenticanze:

```powershell
$env:PYTHONUTF8 = 1
```

Per il terminale, code page UTF-8 (altrimenti i nomi accentati nei report appaiono corrotti — problema di visualizzazione, non di correttezza):

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

Per renderlo permanente, aggiungilo al profilo PowerShell (`$PROFILE`).

### 3.6 Antivirus

Windows Defender scansiona ogni file creato dai test. Su una suite che crea molti file e directory temporanei l'impatto è misurabile, e lo è ancora di più su PyInstaller. Se accettabile secondo le policy locali, escludi le directory di lavoro:

```powershell
Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\Programs\Python"
Add-MpPreference -ExclusionPath "$env:TEMP"
```

### 3.7 Terminale

Usa Windows Terminal con PowerShell 7+.

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

Il repository non contiene ancora codice: allo stato attuale è solo documentazione. Questa sezione descrive la struttura delle directory e il bootstrap del package, da eseguire una volta sola.

### 5.1 Layout del repository

Le due implementazioni vivono in due alberi separati, con una terza directory per ciò che condividono:

```text
python/                    package Python — pyproject.toml alla sua radice
  src/<nome-package>/
    __init__.py
    __main__.py            entry point, parsing CLI, exit code
    walker.py              traversal, codice OS-specific
    rules.py               validazione, nessun accesso al filesystem
    planner.py             risoluzione dei rename
  tests/
  pyproject.toml
  requirements.txt         versioni pinnate (runtime)
  requirements-dev.txt     versioni pinnate (sviluppo)

go/                        modulo Go — go.mod alla sua radice
  cmd/<nome-binario>/
  internal/{walker,rules,planner}/

shared/                    fonte unica, nessun codice eseguibile
  testvectors.json         vettori di test (Tech-rules §8)
  ruleset.json             costanti di Tech-rules §1
  schema/report.schema.json

docs/
TestData/
```

Radici separate perché Go vuole `go.mod` alla radice del proprio albero, mentre Python vuole `pyproject.toml` alla radice del proprio. Con entrambi nella root del repository i due toolchain si sovrappongono e ogni strumento di packaging vede file che non gli competono.

Il layout `src/` (invece del package direttamente in `python/`) impedisce che i test importino accidentalmente il codice dalla working directory invece che dal package installato: senza `src/`, `import <nome-package>` funziona anche quando l'installazione è rotta, e i problemi di packaging emergono solo in fase di distribuzione.

Il nome del comando e del package non è ancora deciso — `<nome-package>` è un segnaposto, da fissare sulle Dev notes prima di creare la directory.

**Le parti comuni sono dati, non codice.** Le regole di naming non possono essere una libreria condivisa: sarebbero comunque due implementazioni. Ciò che deve esistere in una sola copia sono le fixture e le costanti — Dev notes §7 è esplicito, *"a single `testvectors.json` in the repo, consumed by both test suites. Neither implementation carries its own copy"*, e nessuna delle due implementazioni è autoritativa sul comportamento. Per questo `shared/` sta al livello più alto e non dentro una delle due.

### 5.2 `pyproject.toml`

Da dentro `python/`. Struttura minima, con la configurazione dei tool nello stesso file:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<nome-package>"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "unicodedata2==16.0.0",     # versione da fissare e non muovere: vedi §1
]

[project.scripts]
"<nome-comando>" = "<nome_package>.__main__:main"

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PTH", "RUF"]

[tool.mypy]
python_version = "3.13"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`requires-python` con l'upper bound è la trasposizione del pin di §1: impedisce che l'ambiente venga ricreato su una minor diversa senza che nessuno se ne accorga.

### 5.3 Installazione delle dipendenze

Con il venv attivo, da dentro `python/`:

```bash
pip install -e ".[dev]"
```

oppure, se preferisci tenere i requirements separati:

```bash
pip install -e .
pip install -r requirements-dev.txt
```

`requirements-dev.txt`:

```text
pytest
pytest-cov
ruff
mypy
```

L'installazione in editable (`-e`) fa sì che le modifiche al sorgente siano visibili senza reinstallare.

**Congela le versioni** dopo il primo setup funzionante, e versiona il risultato:

```bash
pip freeze > requirements.lock.txt
```

Verifica subito che `unicodedata2` sia quello effettivamente in uso e non lo stdlib:

```bash
python -c "import unicodedata2 as u; print(u.unidata_version)"
python -c "import unicodedata as u; print(u.unidata_version)"   # può differire: è normale
```

Il primo valore è quello che deve finire nell'header del report (Dev notes §3.1, §7).

### 5.4 `.gitattributes`

Necessario perché la parità byte-per-byte non dipenda dalla configurazione git della singola macchina:

```gitattributes
* text=auto eol=lf
shared/**  -text
*.json     -text
*.jsonl    -text
*.py       text eol=lf
*.go       text eol=lf
*.ps1      text eol=crlf
*.bat      text eol=crlf
```

L'intero contenuto di `shared/` e i file `.jsonl` sono marcati binari di proposito: sono confrontati byte per byte dai test di parità e non devono subire alcuna conversione.

### 5.5 `.gitignore`

Il `.gitignore` esistente copre già Python (`__pycache__/`, `*.egg-info/`, `.venv`, `.mypy_cache/`, `.coverage`, `build/`, `dist/`). Vanno aggiunte le voci mancanti:

```gitignore
.pytest_cache/
.ruff_cache/
*.spec
```

Attenzione: `.venv` è già coperto, ma **`.python-version` non va ignorato** — è il pin dell'interprete (§2.2) e deve essere versionato.

---

## 6. Verifica dell'ambiente

Comandi identici sulle due piattaforme, da eseguire **da dentro `python/`** con il venv attivo:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

Con copertura:

```bash
pytest --cov=src --cov-report=term-missing
```

Un solo test, in modo verboso:

```bash
pytest tests/test_rules.py::test_reserved_names -v
```

### 6.1 Test su TestData

`TestData/` contiene nomi non conformi reali e sta nella root del repository: da `python/` il path risale di un livello. Le regole d'uso sono vincolanti:

- **Tool di sola lettura** (`check`, report): usare direttamente il path sorgente.

  ```bash
  python -m <nome_package> check ../TestData
  ```

- **Tool che scrivono** (`plan`/`apply`, rename): lavorare **sempre** su una copia in directory temporanea, mai sull'originale.

  ```bash
  cp -R ../TestData "$SCRATCHPAD/TestData"
  python -m <nome_package> apply "$SCRATCHPAD/TestData" --apply
  ```

  Su Windows:

  ```powershell
  Copy-Item -Recurse ..\TestData "$env:TEMP\TestData"
  python -m <nome_package> apply "$env:TEMP\TestData" --apply
  ```

Ricorda che `--apply` è opt-in: il default è dry-run (Dev notes §6.3).

Nei test, usa la fixture `tmp_path` di pytest per le copie: è per-test, viene ripulita automaticamente e non richiede gestione manuale.

### 6.2 Exit code

Utile in fase di verifica: `check` restituisce **1** quando trova violazioni, e questo non è un errore. Non confonderlo con un crash quando scripti il tool o configuri la CI.

```bash
python -m <nome_package> check ../TestData; echo "exit: $?"
```

```powershell
python -m <nome_package> check ..\TestData; echo "exit: $LASTEXITCODE"
```

La tabella completa dei codici è nelle Dev notes §9.

### 6.3 Parità con l'implementazione Go

Il controllo che conta davvero non è che i test Python passino, ma che le due implementazioni producano lo stesso output (Dev notes §7). In locale, dalla root del repository:

```bash
python -m <nome_package> check TestData --emit-manifest > /tmp/py.jsonl
go -C go run ./cmd/<nome-binario> check ../TestData --emit-manifest > /tmp/go.jsonl
diff /tmp/py.jsonl /tmp/go.jsonl
```

Qualsiasi differenza è un bug in una delle due. Le cause ricorrenti sono in §9.

---

## 7. Distribuzione ai clienti

Diversamente da Go, Python non produce un binario statico: il cliente non deve però installare un interprete. PyInstaller impacchetta interprete e dipendenze in un singolo eseguibile.

```bash
pip install pyinstaller
pyinstaller --onefile --name <nome-comando> src/<nome_package>/__main__.py
```

Due cose da sapere:

- **Niente cross-compilazione.** PyInstaller costruisce solo per la piattaforma su cui gira: serve una macchina (o un runner CI) per ogni target. È la differenza operativa più rilevante rispetto a Go, che cross-compila da un solo host.
- **Stesso attrito di firma.** Dev notes §8: SmartScreen su Windows e Gatekeeper su macOS si applicano identici. Su macOS, notarizzazione con Developer ID, oppure documentare `xattr -d com.apple.quarantine`. Su Windows, certificato di code signing oppure distribuzione via share interno.

Se `ruleset.json` da `shared/` deve finire nel bundle, va dichiarato esplicitamente — PyInstaller non lo include da solo:

```bash
pyinstaller --onefile --add-data "../shared/ruleset.json:." src/<nome_package>/__main__.py
```

Il separatore è `:` su macOS/Linux e `;` su Windows. A runtime il file va cercato in `sys._MEIPASS` quando l'app è bundled.

---

## 8. Configurazione dell'editor

### VS Code

Estensioni **Python** (`ms-python.python`), **Pylance**, **Ruff** (`charliermarsh.ruff`). `.vscode/` è in `.gitignore`, quindi la configurazione resta locale:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/python/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["python/tests"],
  "python.analysis.typeCheckingMode": "strict",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": { "source.organizeImports": "explicit" }
  },
  "files.eol": "\n",
  "files.encoding": "utf8"
}
```

Su Windows, l'interprete è `${workspaceFolder}/python/.venv/Scripts/python.exe`.

`files.eol: "\n"` è rilevante su Windows: evita che l'editor introduca CRLF nei file di test o nelle fixture.

---

## 9. Riepilogo delle differenze tra piattaforme

| Aspetto | macOS | Windows |
| --- | --- | --- |
| Installazione | `brew install python@3.13` o pyenv | `winget install Python.Python.3.13` |
| Attivazione venv | `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| Case-sensitivity FS | APFS case-**in**sensitive di default; serve volume dedicato per alcuni test | NTFS case-insensitive; stesso limite |
| Long paths | `PATH_MAX` 1024 byte, non modificabile | `LongPathsEnabled=1` + interprete manifest-aware + `core.longpaths true` |
| Line endings | nessuna azione | `core.autocrlf false` + `.gitattributes` + `newline="\n"` in `open()` |
| Encoding default di `open()` | UTF-8 | code page ANSI: `encoding="utf-8"` sempre esplicito |
| Nomi non-UTF-8 su disco | non creabili | non creabili |
| Antivirus | — | escludere le directory di lavoro |
| Encoding terminale | UTF-8 di default | code page da impostare a UTF-8 |
| Distribuzione | build su macchina macOS | build su macchina Windows |

---

## 10. Problemi ricorrenti

| Sintomo | Causa | Rimedio |
| --- | --- | --- |
| `python: command not found` dopo l'installazione | PATH non ricaricato, o venv non attivo | nuova sessione; `source .venv/bin/activate` |
| `ModuleNotFoundError` sul package del progetto | installato senza `-e`, o venv sbagliato | §5.3; verifica con `which python` |
| `Activate.ps1 cannot be loaded` | execution policy di PowerShell | §3.2 |
| Test di parità falliscono solo su Windows | CRLF introdotti da git o da `open()` in text mode | §3.4 — `.gitattributes` **e** `newline="\n"` |
| Report illeggibile o con BOM | `encoding` non esplicito, o `utf-8-sig` | §3.5 |
| Fixture con path lunghi non si creano | long paths disattivati o interprete non manifest-aware | §3.3 |
| Test su collisioni case-only falliscono su macOS | volume case-insensitive | §2.4, o skip esplicito nel test |
| Nomi accentati corrotti nel report a terminale | code page non UTF-8 | §3.5 — visualizzazione, non correttezza |
| Output diverso tra due macchine Python | minor di CPython o `unicodedata2` diverse | §1 — la coppia definisce il comportamento |
| Output Python ≠ output Go | tabelle Unicode disallineate, o `str.lower()` al posto di `casefold()` | confronta `unicode_version` negli header; Dev notes §3.2 |
| `TypeError: Object of type ... is not JSON serializable` su path Linux | lone surrogate da `surrogateescape` | Dev notes §4.1 — campo `path_b64` |
