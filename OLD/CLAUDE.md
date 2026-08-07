# SafePath-Checker

Tool Python da riga di comando per analizzare i nomi di file e cartelle all'interno di un percorso e segnalare all'amministratore eventuali nomi che possono compromettere la corretta sincronizzazione tra sistemi eterogenei (macOS / Windows / Linux).

## Obiettivo

Scansionare ricorsivamente un percorso fornito dall'utente ed estrarre tutti i path che contengono caratteri o anomalie problematiche per la portabilità/sincronizzazione cross-platform, producendo un report leggibile dall'amministratore.

## Esempio naming convention vecchia

Nel file `OLD-FileNaming.md` trovi delle indicazioni che avevo lasciato io ai clienti in precedenza, su come comportarsi quando nominano file e directory.

## Specifica tecnica naming

Il file `FileNaming-Technical.md` contiene la specifica tecnica completa dei vincoli sui nomi di file e cartelle (caratteri vietati, nomi riservati, normalizzazione Unicode, lunghezze, case sensitivity, ecc.) con la mappatura delle severità (`error` / `warning` / `info`). È la base normativa di riferimento per i controlli implementati dal tool.

## Controlli da eseguire sui nomi

- **Caratteri non validi su Windows**: `< > : " / \ | ? *` e caratteri di controllo (0x00–0x1F).
- **Nomi riservati Windows**: `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` (anche con estensione).
- **Spazi o punti all'inizio/fine** del nome (es. `"file "`, `"file."`, `" file"`).
- **Caratteri non stampabili / non-ASCII problematici** (es. caratteri di controllo, zero-width, BOM).
- **Forme Unicode diverse** (NFC vs NFD): macOS usa NFD per default, Windows/Linux NFC — segnalare nomi con normalizzazione non-NFC.
- **Lunghezza eccessiva** del nome (>255 byte) o del path complessivo (>260 caratteri per compatibilità Windows classica).  Per calcolo lunghezza eccessiva affidabile, l'utente deve fornire il base-path.
- **Nomi duplicati case-insensitive** nella stessa cartella (problematici su Windows/macOS HFS+ ma validi su Linux).
- **Slash/backslash o due punti** all'interno del nome (oltre al separatore di path).
- **Emoji o simboli** che possono causare problemi su alcuni filesystem (segnalazione opzionale).

## Requisiti del tool

- CLI Python (>=3.10).
- Solo libreria standard quando possibile; aggiungere dipendenze solo se giustificato.
- Output strutturato: di default tabella leggibile a terminale; opzione per export in JSON/CSV.
- Output/funzionalità opzionale: Invio del risultato scansione via Email
- Per ogni problema segnalato: path assoluto, tipo di problema, gravità (`error` / `warning`), descrizione breve.
- Modalità read-only: il tool non rinomina né modifica nulla, solo segnala.
- Gestire correttamente symlink (non seguirli per default) e permessi negati (segnalare e continuare).

## Convenzioni di sviluppo

- Codice e identificatori in inglese; messaggi utente/report in italiano.
- Niente commenti che descrivono *cosa* fa il codice — solo *perché*, quando non ovvio.
- Test con `pytest` su casi rappresentativi (nomi con spazi finali, caratteri Windows-invalid, nomi riservati, NFD vs NFC, ecc.).  La cartella `TestData` contiene dati reali di test su cui poter fare prove.
