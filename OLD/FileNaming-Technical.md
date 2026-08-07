# File Naming — Specifica tecnica per portabilità cross-platform

Specifica tecnica dei vincoli sui nomi di file e cartelle per garantire portabilità e sincronizzazione affidabile fra filesystem eterogenei (Windows NTFS/exFAT, macOS APFS/HFS+, Linux ext4/btrfs/xfs) e servizi di sincronizzazione cloud (OneDrive, Dropbox, Google Drive, SharePoint, Nextcloud, Syncthing).

Questo documento è la base normativa per i controlli implementati da SafePath-Checker.

---

## 1. Caratteri vietati

### 1.1 Caratteri non validi su Windows (NTFS / exFAT)
Severità: **error**

I seguenti caratteri ASCII sono rifiutati dall'API Win32 e devono essere assenti da qualsiasi componente del path:

```
<  >  :  "  /  \  |  ?  *
```

Note:
- `/` e `\` sono ammessi solo come separatori di path, mai all'interno di un singolo segmento.
- `:` è ammesso solo come separatore drive-letter (`C:`) su Windows.

### 1.2 Caratteri di controllo
Severità: **error**

Codepoint Unicode `U+0000`–`U+001F` e `U+007F` (DEL). Rifiutati da Win32 e fonte di corruzione su molti filesystem POSIX.

### 1.3 Caratteri Unicode problematici
Severità: **warning**

- Zero-width: `U+200B` (ZWSP), `U+200C` (ZWNJ), `U+200D` (ZWJ), `U+FEFF` (BOM/ZWNBSP).
- Bidirectional override: `U+202A`–`U+202E`, `U+2066`–`U+2069`.
- Soft hyphen: `U+00AD`.
- Non-breaking space: `U+00A0` (visivamente indistinguibile da uno spazio normale).
- Caratteri della Private Use Area: `U+E000`–`U+F8FF`.

Causano nomi visivamente identici ma binariamente diversi, generando duplicati invisibili e fallimenti nel matching.

### 1.4 Emoji e simboli pittografici
Severità: **warning** (opzionale)

Range principali: `U+1F300`–`U+1FAFF`, `U+2600`–`U+27BF`. Supportati dai filesystem moderni ma frequentemente rotti da:
- Tool legacy e script di backup.
- Indicizzatori e antivirus.
- Trasporti che assumono Latin-1 / Windows-1252.

---

## 2. Nomi riservati

### 2.1 Device names Windows
Severità: **error**

Riservati indipendentemente dall'estensione (`CON.txt` è equivalente a `CON`):

```
CON   PRN   AUX   NUL
COM1  COM2  COM3  COM4  COM5  COM6  COM7  COM8  COM9
LPT1  LPT2  LPT3  LPT4  LPT5  LPT6  LPT7  LPT8  LPT9
```

Confronto case-insensitive.

### 2.2 Nomi speciali POSIX
Severità: **error** se utilizzati come nome completo

`.` e `..` sono entry di directory; non possono essere nomi file.

---

## 3. Vincoli posizionali (inizio/fine nome)

### 3.1 Spazio finale
Severità: **error**

Windows tronca silenziosamente gli spazi finali; il file creato con `"foo "` viene aperto come `"foo"`. Causa di mancata sincronizzazione e di duplicati fantasma.

### 3.2 Punto finale
Severità: **error**

Stessa semantica del punto 3.1: Windows rimuove i punti finali. `"file."` diventa `"file"`.

### 3.3 Spazio iniziale
Severità: **warning**

Tecnicamente valido sulla maggior parte dei filesystem ma spesso troncato da tool di gestione, web upload form, e copia-incolla da browser.

### 3.4 Punto iniziale
Severità: **info**

Convenzione POSIX per file nascosti. Non un errore, ma su Windows non produce l'effetto atteso e può confondere gli utenti.

### 3.5 Tilde iniziale o `$` iniziale
Severità: **warning**

Convenzionalmente usati da Office/Windows per file di lock temporanei (`~$documento.docx`). Da evitare per file persistenti.

---

## 4. Normalizzazione Unicode

Severità: **warning**

macOS (HFS+ storicamente, APFS in alcuni casi) memorizza i nomi in forma **NFD** (decomposta): `é` → `e` + `U+0301`.
Windows e Linux usano normalmente **NFC** (composta): `é` → `U+00E9`.

Conseguenza: lo stesso nome visivo produce sequenze di byte diverse, causando:
- Duplicati cross-platform durante la sincronizzazione.
- Fallimenti di matching in tool che non normalizzano.
- Path "non trovati" quando ci si sposta fra sistemi.

**Regola**: tutti i nomi devono essere in forma **NFC**. SafePath-Checker segnala ogni nome la cui rappresentazione NFC differisce da quella memorizzata.

---

## 5. Lunghezze

### 5.1 Lunghezza del singolo nome
Severità: **error** se >255 byte (UTF-8), **warning** se >255 caratteri.

Limite tipico `NAME_MAX` su ext4, APFS, NTFS: 255 byte o 255 caratteri UTF-16 a seconda del filesystem.

### 5.2 Lunghezza del path completo
Severità: **error** se >260 caratteri (limite `MAX_PATH` Windows classico), **warning** se >240.

Il limite richiede il base-path di riferimento per essere calcolato in modo affidabile (vedi CLAUDE.md). Windows 10/11 supporta path lunghi solo se:
- Il valore di registro `LongPathsEnabled` è impostato a 1, **e**
- L'applicazione dichiara il supporto nel manifest.

La maggior parte dei tool di sincronizzazione (incluso OneDrive in alcune configurazioni) non rispetta questa estensione. Mantenersi sotto 260 caratteri è la scelta sicura.

### 5.3 Componenti annidati eccessivamente
Severità: **warning**

Profondità >20 livelli di directory è un segnale di struttura patologica; spesso indica archivi annidati per errore.

---

## 6. Case sensitivity

### 6.1 Duplicati case-insensitive nella stessa directory
Severità: **error**

Esempio: `Report.pdf` e `report.pdf` nello stesso folder.
- Validi su ext4, APFS case-sensitive.
- Collidono su NTFS, exFAT, APFS case-insensitive (default macOS), HFS+ case-insensitive.

Durante la sincronizzazione uno dei due viene sovrascritto o rinominato con suffisso conflict.

### 6.2 Differenze solo di case fra cartelle
Severità: **warning**

Stessa logica del 6.1 applicata a directory.

---

## 7. Separatori interni anomali

### 7.1 Slash, backslash, due punti dentro al segmento
Severità: **error**

Già coperti dal punto 1.1; ribaditi qui perché frequente fonte di confusione quando provengono da copia-incolla di stringhe contenenti separatori non interpretati come tali (es. `01/02/2026` in un nome file).

### 7.2 Spazi multipli consecutivi
Severità: **info**

Validi ma visivamente ambigui. Possono indicare residui di copia-incolla.

---

## 8. Origine dei problemi: copia-incolla

Il copia-incolla è la sorgente prevalente di:
- Caratteri zero-width e BOM ereditati da pagine web.
- Non-breaking space al posto di spazi normali.
- Spazi finali invisibili dopo selezione di celle in fogli di calcolo.
- Quote tipografiche (`U+2018`, `U+2019`, `U+201C`, `U+201D`) al posto di apici ASCII.
- Sequenze NFD provenienti da macOS incollate su sistemi NFC.

**Mitigazione operativa**: passaggio intermedio in un editor di testo che mostri i caratteri non stampabili (Sublime Text, Notepad++, VS Code con estensione `Gremlins`). Evitare TextEdit, Word, Blocco note: normalizzano o nascondono i caratteri problematici senza segnalarli.

---

## 9. Set di caratteri raccomandato

Per nomi destinati alla massima portabilità (es. archivi a lungo termine, scambio con sistemi legacy):

```
A-Z   a-z   0-9
_     -     .     ( )   [ ]
spazio (eccetto in posizione iniziale/finale)
```

Tutto ciò che eccede questo set è tecnicamente ammesso sui filesystem moderni ma aumenta la superficie di rischio. SafePath-Checker non considera errore l'uso di caratteri fuori da questo set se non rientrano nei punti 1–7; può essere aggiunta una modalità "strict ASCII" che li segnala come warning.

---

## 10. Tabella riassuntiva severità

| # | Controllo | Severità |
|---|---|---|
| 1.1 | Caratteri Windows-invalid (`<>:"/\|?*`) | error |
| 1.2 | Caratteri di controllo `U+0000`–`U+001F`, `U+007F` | error |
| 1.3 | Zero-width, bidi override, NBSP, BOM | warning |
| 1.4 | Emoji / pittogrammi | warning (opt) |
| 2.1 | Device names Windows (CON, PRN, …) | error |
| 2.2 | Nomi `.` / `..` | error |
| 3.1 | Spazio finale | error |
| 3.2 | Punto finale | error |
| 3.3 | Spazio iniziale | warning |
| 3.4 | Punto iniziale | info |
| 3.5 | `~` o `$` iniziali | warning |
| 4 | Non-NFC (NFD o altre forme) | warning |
| 5.1 | Nome >255 byte | error |
| 5.2 | Path >260 caratteri | error |
| 5.3 | Profondità >20 livelli | warning |
| 6.1 | Duplicati case-insensitive (file) | error |
| 6.2 | Duplicati case-insensitive (directory) | warning |
| 7.2 | Spazi multipli consecutivi | info |
| 9 | Caratteri fuori dal set portabile | warning (modalità strict) |
