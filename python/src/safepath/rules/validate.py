"""Validazione dei nomi contro il Profilo B.

Nessuna funzione di questo modulo accede al filesystem: riceve nomi e path gia'
estratti dal walker e restituisce violazioni. E' cio' che rende i risultati
identici su ogni piattaforma (Development guidelines §1).
"""

from dataclasses import dataclass
from enum import Enum

from . import codes as c
from .charset import (
    collision_key,
    is_allowed,
    is_alnum,
    is_combining_mark,
    is_nfc,
    is_reserved_basename,
    is_reserved_extension,
    is_windows_device,
    split_extension,
    to_nfd,
)
from .constants import (
    COMPONENT_MAX_BYTES,
    DIR_NAME_MAX_CHARS,
    DIR_PATH_MAX_CHARS,
    FILE_NAME_MAX_CHARS,
    MAX_DEPTH,
    REL_PATH_MAX_CHARS,
)


class Kind(Enum):
    """Distingue file e directory, che hanno limiti di lunghezza diversi."""

    FILE = "file"
    DIR = "dir"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Target:
    """Entry da validare.

    ``rel_path`` e' relativo alla scan root con separatori "/", nella forma
    trovata su disco (non normalizzata): la normalizzazione e' cio' che CHR-002
    deve poter rilevare.
    """

    rel_path: str
    kind: Kind
    valid_utf8: bool = True


def validate_component(name: str, kind: Kind) -> list[str]:
    """Verifica un singolo componente contro charset, regole posizionali, nomi
    riservati e limiti di lunghezza che dipendono dal solo componente.

    I limiti che dipendono dal path intero (LEN-001, LEN-002, LEN-006) e
    l'unicita' (UNQ-001) non sono verificabili qui: vedi :func:`validate_path` e
    :func:`check_collisions`.

    I codici restituiti sono ordinati e deduplicati (§5).
    """
    if not name:
        return [c.PTH_001]

    found: set[str] = set()
    found.update(_check_charset(name))
    found.update(_check_positional(name))
    found.update(_check_reserved(name))
    found.update(_check_component_length(name, kind))
    return sorted(found)


def _check_charset(name: str) -> list[str]:
    """Verifica il set di caratteri e la forma NFC (§2, §5)."""
    out = []
    if _has_forbidden_char(name):
        out.append(c.CHR_001)
    if not is_nfc(name):
        out.append(c.CHR_002)
    return out


def _has_forbidden_char(name: str) -> bool:
    """Riporta se ``name`` contiene un carattere fuori Profilo B.

    §2.3 vieta i marchi combinanti "standalone", non ogni marchio: in una
    sequenza NFD come "a"+U+0300 il marchio segue una base valida, e la sequenza
    e' gia' segnalata da CHR-002. Segnalare anche CHR-001 renderebbe
    irraggiungibile il vettore normativo di §8 per "Città" scritta in NFD.
    """
    prev_is_base = False
    for ch in name:
        if is_combining_mark(ch):
            if not prev_is_base:
                return True  # marchio senza base: standalone
            # La base resta valida: piu' marchi possono seguirla.
        elif not is_allowed(ch):
            return True
        else:
            prev_is_base = is_alnum(ch)
    return False


def _check_positional(name: str) -> list[str]:
    """Verifica le otto regole posizionali di §3.

    L'ordine dei controlli non influenza l'output: i codici sono ordinati dal
    chiamante.
    """
    out = []
    if name.startswith("._"):
        out.append(c.POS_004)
    if name.startswith("."):
        out.append(c.POS_001)
    if name.endswith((".", ",")):
        out.append(c.POS_002)

    # Lo spazio va cercato anche in coda al basename, non solo al componente:
    # "Riepilogo trimestrale .md" e' POS-003 nei vettori di §8, e la tabella di
    # rewrite §9 lo corregge in "Riepilogo trimestrale.md". Windows trimma lo
    # spazio prima dell'estensione esattamente come quello finale.
    base, _ = split_extension(name)
    if name.startswith(" ") or name.endswith(" ") or base.endswith(" "):
        out.append(c.POS_003)

    if name.startswith("-"):
        out.append(c.POS_005)
    if name.startswith("~"):
        out.append(c.POS_006)
    if "  " in name:
        out.append(c.POS_007)
    if ".." in name:
        out.append(c.POS_008)
    return out


def _check_reserved(name: str) -> list[str]:
    """Verifica device name, basename ed estensioni riservate (§4)."""
    out = []
    if is_windows_device(name):
        out.append(c.RSV_001)
    if is_reserved_basename(name):
        out.append(c.RSV_002)
    _, ext = split_extension(name)
    if ext and is_reserved_extension(ext):
        out.append(c.RSV_003)
    return out


def _check_component_length(name: str, kind: Kind) -> list[str]:
    """Verifica i limiti in caratteri e byte del componente (LEN-003..LEN-005).

    Entrambi i conteggi sono fatti su NFD, che e' il caso peggiore: un accento
    precomposto diventa due code point e fino a tre byte in piu' (§1, §5).
    """
    out = []
    nfd = to_nfd(name)

    if kind is Kind.DIR:
        if len(nfd) > DIR_NAME_MAX_CHARS:
            out.append(c.LEN_004)
    elif len(nfd) > FILE_NAME_MAX_CHARS:
        out.append(c.LEN_003)

    if len(nfd.encode("utf-8", "surrogateescape")) > COMPONENT_MAX_BYTES:
        out.append(c.LEN_005)
    return out


def validate_path(t: Target) -> list[str]:
    """Valida un'entry completa: il componente finale piu' i limiti che
    dipendono dal path nel suo insieme (LEN-001, LEN-002, LEN-006).

    La scan root non e' validata come componente: solo il suo contenuto (§2.1).
    ``rel_path`` e' quindi gia' relativo alla root.

    Per un'entry con ``valid_utf8`` falso restituisce CHR-001 senza ulteriore
    analisi, perche' i byte non sono interpretabili come nome (§7.1).
    """
    if not t.rel_path:
        return [c.PTH_001]
    if not t.valid_utf8:
        return [c.CHR_001]

    found: set[str] = set()

    # Le regole di §2-§4 si applicano a un componente per volta: un file non
    # eredita le violazioni del nome della directory che lo contiene, che ha
    # gia' la propria riga nel report. Ripeterle su ogni discendente gonfierebbe
    # i conteggi e renderebbe illeggibile un albero profondo.
    found.update(validate_component(t.rel_path.split("/")[-1], t.kind))

    # I limiti che dipendono dal path nel suo insieme appartengono invece
    # all'entry: e' il suo path a essere troppo lungo o troppo profondo.
    found.update(_check_path_length(t))
    found.update(_check_depth(t))
    return sorted(found)


def _check_path_length(t: Target) -> list[str]:
    """Verifica LEN-001 e LEN-002, in caratteri sulla forma NFD."""
    out = []
    if len(to_nfd(t.rel_path)) > REL_PATH_MAX_CHARS:
        out.append(c.LEN_001)

    # La porzione di directory e' il path senza il componente finale e senza
    # separatore in coda. Per un'entry nella root e' vuota.
    i = t.rel_path.rfind("/")
    dir_part = t.rel_path[:i] if i >= 0 else ""
    if len(to_nfd(dir_part)) > DIR_PATH_MAX_CHARS:
        out.append(c.LEN_002)
    return out


def _check_depth(t: Target) -> list[str]:
    """Verifica LEN-006.

    La profondita' e' il numero di livelli di directory sotto la scan root,
    contata dal path argument e non dalla root del filesystem (§2.1, §7.3).
    """
    depth = t.rel_path.count("/")
    # Per una directory, il componente finale e' esso stesso un livello.
    if t.kind is Kind.DIR:
        depth += 1
    return [c.LEN_006] if depth > MAX_DEPTH else []


def check_collisions(names: list[str]) -> set[str]:
    """Individua le collisioni case-insensitive fra i nomi di una singola
    directory e restituisce l'insieme dei nomi coinvolti (§5, UNQ-001).

    ``names`` e' il listing di una sola directory: il confronto fra directory
    diverse non ha significato. La chiave e' ``casefold(NFC(name))`` (§6.2).
    """
    by_key: dict[str, list[str]] = {}
    for n in names:
        by_key.setdefault(collision_key(n), []).append(n)

    colliding: set[str] = set()
    for group in by_key.values():
        if len(group) > 1:
            colliding.update(group)
    return colliding
