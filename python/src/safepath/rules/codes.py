"""Codici di violazione e relative descrizioni (File naming Tech-rules §7)."""

#: Revisione delle regole implementate. Compare nell'header dei report ed e'
#: confrontata dai test di parita' (Development guidelines §10).
RULESET_VERSION = "1"

CHR_001 = "CHR-001"  # carattere fuori Profilo B
CHR_002 = "CHR-002"  # nome non in forma NFC
POS_001 = "POS-001"  # punto iniziale
POS_002 = "POS-002"  # punto o virgola finale
POS_003 = "POS-003"  # spazio iniziale o finale
POS_004 = "POS-004"  # prefisso AppleDouble "._"
POS_005 = "POS-005"  # trattino iniziale
POS_006 = "POS-006"  # tilde iniziale
POS_007 = "POS-007"  # spazi consecutivi
POS_008 = "POS-008"  # punti consecutivi
RSV_001 = "RSV-001"  # nome di device Windows
RSV_002 = "RSV-002"  # basename riservato
RSV_003 = "RSV-003"  # estensione riservata
LEN_001 = "LEN-001"  # path relativo troppo lungo
LEN_002 = "LEN-002"  # porzione directory troppo lunga
LEN_003 = "LEN-003"  # nome file troppo lungo (caratteri)
LEN_004 = "LEN-004"  # nome directory troppo lungo (caratteri)
LEN_005 = "LEN-005"  # componente troppo lungo (byte, NFD)
LEN_006 = "LEN-006"  # profondita' eccessiva
UNQ_001 = "UNQ-001"  # collisione case-insensitive
PTH_001 = "PTH-001"  # path vuoto

#: Descrizione italiana di ogni codice, usata nella colonna detail (§3.1).
DESCRIPTIONS: dict[str, str] = {
    CHR_001: "carattere non ammesso dal Profilo B",
    CHR_002: "nome non in forma normale NFC",
    POS_001: "il nome inizia con un punto",
    POS_002: "il nome termina con un punto o una virgola",
    POS_003: "il nome inizia o termina con uno spazio",
    POS_004: 'il nome inizia con il prefisso AppleDouble "._"',
    POS_005: "il nome inizia con un trattino",
    POS_006: "il nome inizia con una tilde",
    POS_007: "il nome contiene spazi consecutivi",
    POS_008: "il nome contiene punti consecutivi",
    RSV_001: "nome riservato di device Windows",
    RSV_002: "basename riservato di sistema",
    RSV_003: "estensione riservata",
    LEN_001: "path relativo troppo lungo",
    LEN_002: "porzione di directory del path troppo lunga",
    LEN_003: "nome file troppo lungo",
    LEN_004: "nome directory troppo lungo",
    LEN_005: "componente troppo lungo in byte (UTF-8 di NFD)",
    LEN_006: "profondita' di annidamento eccessiva",
    UNQ_001: "collisione case-insensitive con un altro nome nella stessa directory",
    PTH_001: "path vuoto",
}


def describe(code: str) -> str:
    """Restituisce la descrizione italiana di un codice di violazione.

    Per un codice sconosciuto restituisce il codice stesso, cosi' che un report
    resti leggibile anche se il codice non e' ancora mappato.
    """
    return DESCRIPTIONS.get(code, code)


def describe_codes(codes: list[str]) -> str:
    """Compone la colonna detail a partire dai codici di una riga.

    E' il campo umano: quello leggibile dalle macchine e' ``codes``, che non va
    mai ricavato da qui (§3.1).
    """
    return "; ".join(describe(c) for c in codes)
