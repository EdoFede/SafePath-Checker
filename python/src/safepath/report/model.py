"""Modello del report: righe, riepilogo e intestazione.

Le righe non possono essere emesse mano a mano che il walk procede: escono
ordinate e non in ordine di scoperta, quindi vanno accumulate, ordinate e solo
allora emesse (Development guidelines §5).
"""

from dataclasses import dataclass, field
from enum import Enum

#: Forma del report. Compare nell'header ed e' confrontata dai test di parita'
#: (§10).
SCHEMA_VERSION = "1"


class Outcome(Enum):
    """Cio' che il filesystem ha confermato dopo la ri-lettura (§3.2)."""

    OK = "ok"
    UNCHANGED = "unchanged"
    ERROR = "error"
    SKIPPED = "skipped"

    def __str__(self) -> str:
        return self.value


class Action(Enum):
    """Cio' che il tool ha deciso di fare (§3.2)."""

    RENAME = "rename"
    NONE = "none"
    MANUAL = "manual"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


@dataclass
class Row:
    """Riga del report: una per entry, sempre, cosi' che il conteggio delle
    righe abbia significato (§3.1)."""

    root: str
    path: str
    type: str
    status: str
    codes: list[str] = field(default_factory=list)
    detail: str = ""

    # Colonne azione, solo per auto-rename (§3.2).
    action: Action | None = None
    new_path: str = ""
    outcome: Outcome | None = None
    outcome_detail: str = ""

    # Presente solo con --show-excluded (§3.4).
    excluded_by: str = ""


@dataclass
class Summary:
    """Conteggi del riepilogo di fine esecuzione (§4.1)."""

    examined: int = 0
    ok: int = 0
    violations: int = 0
    skipped: int = 0
    excluded: int = 0

    # Solo per auto-rename.
    renamed: int = 0
    failed: int = 0
    manual: int = 0


@dataclass
class Options:
    """Opzioni di invocazione riportate nel report, cosi' che sia
    interpretabile a distanza di mesi (§4.3)."""

    show_ok: bool = False
    show_excluded: bool = False
    exclude: list[str] = field(default_factory=list)
    exclude_regex: list[str] = field(default_factory=list)


@dataclass
class Report:
    """Insieme completo di cio' che un'esecuzione produce."""

    schema_version: str
    ruleset_version: str
    unicode_version: str
    tool_version: str
    command: str  # "scan" | "auto-rename"
    generated_at: str  # UTC, RFC 3339
    roots: list[str]
    options: Options = field(default_factory=Options)
    summary: Summary = field(default_factory=Summary)
    rows: list[Row] = field(default_factory=list)

    #: Caratteri fuori profilo privi di sostituzione incontrati durante
    #: l'esecuzione: e' il punto di partenza per estendere ``CHAR_MAP``.
    unmapped: list[tuple[str, int]] = field(default_factory=list)

    #: Distingue le due forme del report. Le colonne azione sono assenti, non
    #: nulle, sotto ``scan``: la loro assenza e' il modo in cui un consumatore
    #: distingue le due forme (§4.3).
    with_actions: bool = False

    def sort(self) -> None:
        """Ordina le righe secondo il contratto di determinismo: le root
        nell'ordine di riga di comando, e all'interno di ogni root il byte order
        del path (§5)."""
        index = {root: i for i, root in enumerate(self.roots)}
        self.rows.sort(key=lambda r: (index.get(r.root, len(index)), r.path))

    def has_blocking(self) -> bool:
        """Riporta se restano violazioni non risolte.

        E' cio' che distingue exit 0 da exit 1 per ``auto-rename``: la domanda
        utile per uno script non e' "c'era qualcosa che non andava?" ma "c'e'
        ancora qualcosa?" (§12).
        """
        return any(r.action in (Action.MANUAL, Action.FAILED) for r in self.rows)
