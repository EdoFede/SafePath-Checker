"""Costruzione del nome conforme a partire da un nome in violazione."""

from .. import rules
from .charmap import replacement


def remediate(name: str, kind: rules.Kind) -> tuple[str, list[str]]:
    """Calcola il nome conforme corrispondente a ``name``, applicando nella
    stessa sequenza le correzioni previste dalla tabella di rewrite di §9.

    Restituisce anche i caratteri fuori profilo privi di sostituzione nella
    mappa: se l'elenco non e' vuoto il nome restituito non e' utilizzabile e
    l'entry va marcata ``manual`` (scelta dell'utente, non del documento).

    Case, spazi singoli e punti interni sono preservati: solo l'elemento in
    violazione viene modificato.
    """
    # NFC prima di tutto: corregge CHR-002 e rende prevedibili i confronti
    # successivi, perche' i caratteri precomposti sono quelli del Profilo B.
    s = rules.to_nfc(name)

    s, unmapped = _apply_char_map(s)
    if unmapped:
        return "", unmapped

    s = _collapse_spaces(s)
    s = _collapse_dots(s)
    s = _fix_reserved(s, kind)
    s = _trim_positional(s)
    return s, []


def _apply_char_map(s: str) -> tuple[str, list[str]]:
    """Sostituisce ogni carattere fuori Profilo B con la traslitterazione
    prevista, raccogliendo quelli che non ne hanno una.

    I marchi combinanti con una base valida sopravvivono alla normalizzazione NFC
    come carattere precomposto e non arrivano qui; un marchio standalone non e'
    mappabile e finisce fra i non mappati.
    """
    out: list[str] = []
    unmapped: list[str] = []
    seen: set[str] = set()

    for ch in s:
        if rules.is_allowed(ch) and not rules.is_combining_mark(ch):
            out.append(ch)
            continue
        repl, ok = replacement(ch)
        if ok:
            out.append(repl)
            continue
        if ch not in seen:
            seen.add(ch)
            unmapped.append(ch)
    return "".join(out), unmapped


def _collapse_spaces(s: str) -> str:
    """Riduce ogni sequenza di spazi a uno solo (POS-007)."""
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def _collapse_dots(s: str) -> str:
    """Riduce ogni sequenza di punti a uno solo (POS-008).

    E' il caso di "Elenco soci S.p.A..pdf" -> "Elenco soci S.p.A.pdf" della
    tabella §9: l'abbreviazione che finisce con un punto, seguita dal punto
    dell'estensione.
    """
    while ".." in s:
        s = s.replace("..", ".")
    return s


def _trim_positional(s: str) -> str:
    """Rimuove i caratteri illegali in testa e in coda: spazi, punti, virgole,
    trattini e tilde (POS-001..POS-006).

    Il ciclo e' necessario perche' una correzione ne puo' scoprire un'altra:
    " .-nome" richiede piu' passate.
    """
    while True:
        before = s

        s = s.strip(" ")
        s = s.lstrip(".-~")
        s = s.rstrip(".,")

        # Lo spazio in coda al basename e' POS-003 quanto quello finale:
        # "Riepilogo trimestrale .md" -> "Riepilogo trimestrale.md" (§9).
        base, ext = rules.split_extension(s)
        if ext:
            trimmed = base.rstrip(" ")
            if trimmed != base:
                s = trimmed + ext

        if s == before:
            return s


def _fix_reserved(s: str, kind: rules.Kind) -> str:
    """Rende non riservato un nome che collide con un device name Windows, un
    basename o un'estensione riservata (§4).

    La strategia segue l'esempio di §9 ("CON.docx" -> "Contratto CON.docx"): si
    antepone un prefisso descrittivo invece di alterare il nome esistente, che
    resta cosi' riconoscibile.
    """
    # I basename riservati di sistema non hanno un contenuto da preservare, ma
    # il rename deve comunque produrre un nome valido.
    if rules.is_reserved_basename(s):
        return "file " + s.lstrip(".")

    if rules.is_windows_device(s):
        # "Contratto" e' il prefisso della tabella §9; per una directory non ha
        # senso e si usa "Cartella", che resta nello stesso registro.
        prefix = "Cartella " if kind is rules.Kind.DIR else "Contratto "
        return prefix + s

    # Estensione riservata: il punto va neutralizzato, altrimenti il file resta
    # un temporaneo agli occhi dei client di sync.
    base, ext = rules.split_extension(s)
    if ext and rules.is_reserved_extension(ext):
        return base + " " + ext.removeprefix(".")
    return s


# Nessuna correzione accorcia il nome. Un nome che resta oltre il limite di
# lunghezza viene rifiutato da resolve_free e l'entry diventa manual: troncare il
# nome di un documento e' un giudizio che il tool non e' autorizzato a dare al
# posto dell'utente (§8.3).
