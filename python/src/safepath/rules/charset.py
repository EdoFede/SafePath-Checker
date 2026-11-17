"""Charset del Profilo B, normalizzazione Unicode ed estrazione dell'estensione.

Le tabelle Unicode arrivano da ``unicodedata2`` e non dallo stdlib: lo stdlib
``unicodedata`` e' legato alla build di CPython e due minor diverse spediscono
tabelle diverse, il che rende impossibile allinearsi a una build Go pinnata
(Development guidelines §6.1).
"""

import unicodedata2

from .constants import (
    LATIN1_SUP_HIGH,
    LATIN1_SUP_HIGH2,
    LATIN1_SUP_LOW,
    LATIN1_SUP_LOW2,
    LATIN_EXT_HIGH,
    LATIN_EXT_LOW,
    PUNCTUATION,
    RESERVED_BASENAMES,
    RESERVED_EXTENSIONS,
    WINDOWS_DEVICE_NAMES,
)

#: Versione delle tabelle Unicode in uso. Compare nell'header del report: due
#: esecuzioni con tabelle diverse non sono confrontabili (§6.1).
UNICODE_VERSION: str = unicodedata2.unidata_version


def is_alnum(ch: str) -> bool:
    """Riporta se ``ch`` e' alfanumerico secondo il Profilo B (§2.1).

    Sono ASCII alfanumerico e le lettere di Latin-1 Supplement / Latin Extended-A.
    """
    if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9"):
        return True
    cp = ord(ch)
    return (
        LATIN1_SUP_LOW <= cp <= LATIN1_SUP_HIGH
        or LATIN1_SUP_LOW2 <= cp <= LATIN1_SUP_HIGH2
        or LATIN_EXT_LOW <= cp <= LATIN_EXT_HIGH
    )


def is_allowed(ch: str) -> bool:
    """Riporta se ``ch`` e' ammesso in una qualsiasi posizione (§2.1).

    Le regole posizionali (§3) sono verificate separatamente: un carattere puo'
    essere ammesso qui e comunque illegale nella posizione in cui compare.
    """
    return is_alnum(ch) or ch in PUNCTUATION


def is_combining_mark(ch: str) -> bool:
    """Riporta se ``ch`` appartiene alla categoria Unicode Mn, vietata dal
    Profilo B (§2.3).

    E' l'unico controllo di ``rules`` che dipende dalla tabella Unicode e non
    dalla sola normalizzazione, ed e' quindi la superficie di rischio di §6.1.
    """
    return bool(unicodedata2.category(ch) == "Mn")


def is_nfc(s: str) -> bool:
    """Riporta se ``s`` e' gia' in forma normale NFC.

    Il controllo e' distinto dalla conversione: convertire silenziosamente
    nasconderebbe le violazioni CHR-002, che sono esattamente gli artefatti
    HFS+/macOS che l'audit deve rilevare (§6.3).

    Il confronto con la forma normalizzata sostituisce ``is_normalized``, che
    ``unicodedata2`` non espone: usare quella dello stdlib rimetterebbe in gioco
    le tabelle legate alla build di CPython, che §6.1 esclude.
    """
    return s == to_nfc(s)


def to_nfc(s: str) -> str:
    """Forma NFC di ``s``, usata sui path scritti nei report e nel manifest.

    Non va mai usata per alterare cio' che viene validato.
    """
    return str(unicodedata2.normalize("NFC", s))


def to_nfd(s: str) -> str:
    """Forma NFD di ``s``, usata per i conteggi di lunghezza.

    I conteggi vanno fatti sul caso peggiore: un accento precomposto diventa due
    code point e fino a tre byte in piu' (§1, §5).
    """
    return str(unicodedata2.normalize("NFD", s))


def split_extension(name: str) -> tuple[str, str]:
    """Separa un componente in basename ed estensione secondo §3.1.

    L'ultimo segmento separato da punto e' un'estensione solo se composto da
    1..10 caratteri alfanumerici ASCII. L'estensione restituita include il punto;
    se non ce n'e' una valida, ``ext`` e' vuota e ``base`` e' il componente intero.

        "Rossi e C. S.p.A.pdf"  -> ("Rossi e C. S.p.A", ".pdf")
        "archivio.tar.gz"       -> ("archivio.tar",     ".gz")
        "Verbale rev. 2"        -> ("Verbale rev. 2",   "")     segmento con spazio
        "Elenco soci S.p.A."    -> ("Elenco soci S.p.A.", "")   segmento vuoto
    """
    i = name.rfind(".")
    if i < 0:
        return name, ""
    seg = name[i + 1 :]
    if not _is_extension_segment(seg):
        return name, ""
    return name[:i], name[i:]


def _is_extension_segment(seg: str) -> bool:
    """Verifica il predicato ``^[A-Za-z0-9]{1,10}$`` di §3.1."""
    if not seg or len(seg) > 10:
        return False
    return all(("A" <= c <= "Z") or ("a" <= c <= "z") or ("0" <= c <= "9") for c in seg)


def device_segment(name: str) -> str:
    """Segmento che precede il primo punto, ambito di confronto dei device (§4).

    "CON.rev 2.docx"             -> "CON"                    (riservato)
    "Documento CON allegati.pdf" -> "Documento CON allegati" (non riservato)
    """
    i = name.find(".")
    return name[:i] if i >= 0 else name


def is_windows_device(name: str) -> bool:
    """Riporta se il segmento prima del primo punto e' un device Win32 (§4)."""
    return device_segment(name).lower() in WINDOWS_DEVICE_NAMES


def is_reserved_basename(name: str) -> bool:
    """Riporta se il componente intero e' un basename riservato (§4)."""
    return name.lower() in RESERVED_BASENAMES


def is_reserved_extension(ext: str) -> bool:
    """Riporta se ``ext``, punto incluso, e' un'estensione riservata (§4)."""
    return ext.lower() in RESERVED_EXTENSIONS


def collision_key(name: str) -> str:
    """Chiave di confronto per l'unicita' case-insensitive: ``casefold(NFC(name))``.

    Il full case folding non e' equivalente al lowercasing e ``str.lower()`` non
    puo' essere usato qui: "ß" diventa "ss" e "ﬁ" diventa "fi" solo con il
    folding. Il Profilo B rifiuta questi caratteri come CHR-001, ma il controllo
    di collisione gira sul dataset pre-remediation, che contiene nomi legacy
    arbitrari (§6.2).

    Il confronto e' valido solo fra nomi della stessa directory.
    """
    return to_nfc(name).casefold()


def fold_pattern(s: str) -> str:
    """Applica lo stesso folding ai pattern di esclusione, per il matching
    case-insensitive di §2.3."""
    return to_nfc(s).casefold()
