"""Tabella e riepilogo su console.

La tabella e' l'output standard del programma ed e' sempre prodotta;
diagnostica, avanzamento ed errori vanno su stderr, cosi' che una redirezione
catturi la sola tabella (§4.1).
"""

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TextIO

from .model import Action, Outcome, Report, Row

#: Larghezza di riferimento quando stdout non e' un terminale, per rendere
#: riproducibile l'elisione delle colonne nei test di parita' (§10).
DEFAULT_WIDTH = 120

# Codici ANSI, usati solo quando use_colour lo consente.
_RESET = "\x1b[0m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_GREEN = "\x1b[32m"
_DIM = "\x1b[2m"

_SEP = 2  # spazi fra colonne
_MIN_TRUNCABLE = 8


@dataclass
class ConsoleOptions:
    """Configura la resa della tabella."""

    width: int = DEFAULT_WIDTH
    use_colour: bool = False


def detect_console_options(stream: TextIO) -> ConsoleOptions:
    """Determina larghezza e colore dall'ambiente.

    Il colore va disattivato quando stdout non e' un TTY, quando ``NO_COLOR`` e'
    impostata o quando ``TERM=dumb``. La tabella deve restare leggibile senza
    colore: nessuna informazione e' codificata nel solo colore (§4.1).
    """
    try:
        is_tty = stream.isatty()
    except (AttributeError, ValueError):
        is_tty = False

    width = DEFAULT_WIDTH
    if is_tty:
        detected = shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns
        if detected > 0:
            width = detected

    # COLUMNS permette ai test di fissare la larghezza senza un terminale.
    columns = os.environ.get("COLUMNS", "")
    if columns:
        try:
            value = int(columns)
        except ValueError:
            value = 0
        if value > 0:
            width = value

    colour = is_tty and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    return ConsoleOptions(width=width, use_colour=colour)


@dataclass
class _Column:
    """Colonna della tabella."""

    title: str
    value: Callable[[Row], str]
    truncable: bool = False  # path, detail e new_path si elidono


def write_console(out: TextIO, r: Report, opts: ConsoleOptions | None = None) -> None:
    """Scrive la tabella e il riepilogo su ``out``."""
    opts = opts or ConsoleOptions()
    if opts.width <= 0:
        opts.width = DEFAULT_WIDTH

    _write_header(out, r)

    if not r.rows:
        # Il silenzio e' indistinguibile da un crash: quando non c'e' nulla da
        # riportare va detto esplicitamente (§4.1).
        out.write("\nNessuna violazione rilevata.\n")
    else:
        _write_table(out, r, opts)

    _write_summary(out, r)
    _write_unmapped(out, r)


def _write_header(out: TextIO, r: Report) -> None:
    """Emette l'intestazione che rende il report riproducibile a distanza di
    mesi: e' cio' che i test di parita' confrontano (§4.1, §10)."""
    out.write(
        f"safepath {r.tool_version}  |  schema {r.schema_version}  |  "
        f"unicode {r.unicode_version}  |  ruleset {r.ruleset_version}\n"
    )
    out.write(f"comando: {r.command}  |  generato: {r.generated_at}\n")
    out.write(f"root: {', '.join(r.roots)}\n")


def _table_columns(r: Report) -> list[_Column]:
    """Costruisce l'elenco di colonne in base alla forma del report.

    L'ordine e' fisso: colonne di findings prima, colonne azione appese (§3).
    """
    cols = [
        _Column("root", lambda x: x.root),
        _Column("path", lambda x: x.path, truncable=True),
        _Column("type", lambda x: x.type),
        _Column("status", lambda x: x.status),
        _Column("codes", lambda x: " ".join(x.codes)),
        _Column("detail", lambda x: x.detail, truncable=True),
    ]
    if r.with_actions:
        cols += [
            _Column("action", lambda x: str(x.action) if x.action else ""),
            _Column("new_path", lambda x: x.new_path, truncable=True),
            _Column("outcome", lambda x: str(x.outcome) if x.outcome else ""),
        ]
    if r.options.show_excluded:
        cols.append(_Column("excluded_by", lambda x: x.excluded_by, truncable=True))
    return cols


def _write_table(out: TextIO, r: Report, opts: ConsoleOptions) -> None:
    """Emette la tabella allineata, elidendo le colonne elidibili quando il
    terminale e' stretto.

    Le larghezze sono l'unica parte dell'output autorizzata a variare fra
    esecuzioni (§4.1, §5).
    """
    cols = _table_columns(r)

    # Larghezza naturale di ogni colonna: il massimo fra titolo e valori.
    widths = [
        max(len(c.title), max((len(c.value(row)) for row in r.rows), default=0)) for c in cols
    ]
    _shrink_to_fit(cols, widths, opts.width)

    out.write("\n")
    _write_row(out, cols, widths, lambda i: cols[i].title, "")
    _write_row(out, cols, widths, lambda i: "-" * widths[i], "")

    for row in r.rows:
        colour = _status_colour(row) if opts.use_colour else ""
        # partial lega la riga corrente senza il default-argument, che
        # nasconderebbe il tipo del callable.
        _write_row(out, cols, widths, partial(_cell_value, cols, row), colour)


def _cell_value(cols: list[_Column], row: Row, i: int) -> str:
    """Estrae il valore della colonna ``i`` per la riga data."""
    return cols[i].value(row)


def _shrink_to_fit(cols: list[_Column], widths: list[int], max_width: int) -> None:
    """Riduce le colonne elidibili finche' la tabella non entra nella larghezza
    disponibile.

    Le colonne root, status e codes non vengono mai troncate (§4.1). Si riduce
    ciclicamente la colonna elidibile piu' larga: cosi' lo spazio tolto e'
    distribuito invece di consumare per intero la prima colonna.
    """

    def total() -> int:
        return _SEP * (len(cols) - 1) + sum(widths)

    while total() > max_width:
        widest, idx = 0, -1
        for i, c in enumerate(cols):
            if c.truncable and widths[i] > _MIN_TRUNCABLE and widths[i] > widest:
                widest, idx = widths[i], i
        if idx < 0:
            return  # nessuna colonna ulteriormente riducibile
        widths[idx] -= 1


def _write_row(
    out: TextIO,
    cols: list[_Column],
    widths: list[int],
    value: Callable[[int], str],
    colour: str,
) -> None:
    """Emette una riga applicando troncamento e allineamento."""
    cells = [_pad(_truncate(value(i), widths[i]), widths[i]) for i in range(len(cols))]
    line = "  ".join(cells).rstrip(" ")

    if colour:
        out.write(f"{colour}{line}{_RESET}\n")
        return
    out.write(line + "\n")


def _truncate(s: str, width: int) -> str:
    """Accorcia ``s`` a ``width`` caratteri segnando il taglio con "…" (§4.1)."""
    if len(s) <= width:
        return s
    if width <= 1:
        return "…"
    return s[: width - 1] + "…"


def _pad(s: str, width: int) -> str:
    """Allinea a sinistra su ``width`` caratteri."""
    return s + " " * max(0, width - len(s))


def _status_colour(row: Row) -> str:
    """Sceglie il colore di una riga.

    Il colore distingue la gravita' ma non veicola informazione da solo: lo
    stato e' comunque nella colonna.
    """
    if row.action is Action.FAILED or row.outcome is Outcome.ERROR:
        return _RED
    if row.status == "violation":
        return _YELLOW
    if row.status in ("skipped", "excluded"):
        return _DIM
    if row.status == "ok":
        return _GREEN
    return ""


def _write_summary(out: TextIO, r: Report) -> None:
    """Emette il riepilogo, che e' cio' che la maggior parte degli utenti legge
    davvero. Va su stdout insieme alla tabella (§4.1)."""
    s = r.summary
    out.write(
        f"\nEsaminate {s.examined} voci: {s.ok} conformi, {s.violations} in violazione, "
        f"{s.skipped} saltate, {s.excluded} escluse.\n"
    )
    if r.with_actions:
        out.write(f"Rinominate {s.renamed}, fallite {s.failed}, da correggere a mano {s.manual}.\n")


def _write_unmapped(out: TextIO, r: Report) -> None:
    """Elenca i caratteri fuori profilo privi di sostituzione.

    E' il punto da cui partire per estendere ``CHAR_MAP``: senza questo elenco,
    le entry rimaste manual non dicono quale riga aggiungere alla mappa.
    """
    if not r.unmapped:
        return

    out.write(f"\nCaratteri fuori profilo senza sostituzione prevista ({len(r.unmapped)}):\n")
    for ch, count in r.unmapped:
        out.write(f"  {ch:<4} U+{ord(ch):04X}  {count} occorrenze\n")
    out.write("Per renderli correggibili, aggiungerli a src/safepath/planner/charmap.py.\n")
