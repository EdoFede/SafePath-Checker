"""Costanti normative del Profilo B (File naming Tech-rules §1, §2, §4)."""

# Limiti di lunghezza e profondita' (§1).
#
# Vale l'invariante DIR_PATH_MAX_CHARS + 1 + FILE_NAME_MAX_CHARS == REL_PATH_MAX_CHARS.
# Tutti i limiti si applicano simultaneamente: nessuno implica gli altri.

#: Limite del path relativo alla scan root. Deriva da 259 (Windows MAX_PATH)
#: - 50 (prefisso riservato) - 25 (suffisso di conflitto NextCloud), arrotondato.
REL_PATH_MAX_CHARS = 180

#: Porzione di directory del path relativo, separatore finale escluso.
DIR_PATH_MAX_CHARS = 115

#: Componente finale di un file, estensione inclusa.
FILE_NAME_MAX_CHARS = 64

#: Nome di un componente directory.
DIR_NAME_MAX_CHARS = 48

#: Componente in byte UTF-8 della forma NFD, con margine su NAME_MAX (255).
COMPONENT_MAX_BYTES = 200

#: Numero massimo di livelli di directory sotto la scan root.
MAX_DEPTH = 6

# Intervalli di caratteri ammessi dal Profilo B (§2.1): Latin-1 Supplement e
# Latin Extended-A, esclusi U+00D7 e U+00F7 (segni di moltiplicazione e
# divisione, non lettere).
LATIN1_SUP_LOW = 0x00C0
LATIN1_SUP_HIGH = 0x00D6
LATIN1_SUP_LOW2 = 0x00D8
LATIN1_SUP_HIGH2 = 0x00F6
LATIN_EXT_LOW = 0x00F8
LATIN_EXT_HIGH = 0x017F

#: Caratteri non alfanumerici ammessi dal Profilo B (§2.1).
PUNCTUATION = " -_.(),"

#: Nomi di device riservati da Win32 (§4). Il confronto e' case-insensitive e
#: avviene sul segmento che precede il primo punto, con o senza cio' che segue.
WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    | {f"com{i}" for i in range(10)}
    | {f"lpt{i}" for i in range(10)}
)

#: Basename riservati, confrontati con il componente intero, case-insensitive (§4).
#: "icon\r" e' l'artefatto Finder di macOS, con un CR letterale in coda.
RESERVED_BASENAMES = frozenset(
    {
        ".ds_store",
        "icon\r",
        ".appledouble",
        ".appledb",
        ".appledesktop",
        ".temporaryitems",
        ".spotlight-v100",
        ".fseventsd",
        ".trashes",
        ".htaccess",
        ".ocdata",
        ".sync-exclude.lst",
        ".snapshot",
        "desktop.ini",
    }
)

#: Estensioni riservate, confrontate con l'estensione di §3.1, punto incluso.
RESERVED_EXTENSIONS = frozenset({".part", ".filepart", ".tmp"})
