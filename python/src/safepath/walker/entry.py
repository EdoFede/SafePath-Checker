"""Entry prodotte dalla scansione e skip di bookkeeping."""

from dataclasses import dataclass, field
from enum import Enum

from .. import rules


class Status(Enum):
    """Stato di un'entry nel report (§3.1)."""

    OK = "ok"
    VIOLATION = "violation"
    SKIPPED = "skipped"
    EXCLUDED = "excluded"

    def __str__(self) -> str:
        return self.value


@dataclass
class Entry:
    """Singola entry incontrata durante la scansione.

    La serializzazione JSONL di una lista di ``Entry`` e' il manifest opzionale
    (§1).
    """

    root: str  # argomento di riga di comando, verbatim
    rel_path: str  # path relativo alla root, NFC, separatori "/"
    kind: rules.Kind
    status: Status = Status.OK

    #: Registra se il nome su disco era gia' in NFC. Convertire silenziosamente
    #: nasconderebbe le violazioni CHR-002, che sono gli artefatti macOS/HFS+
    #: che l'audit deve rilevare (§6.3).
    nfc_normalized: bool = True

    #: Falso per i nomi Linux non decodificabili. ``path_b64`` porta i byte
    #: grezzi, perche' quei nomi non sono rappresentabili in JSON (§7.1).
    valid_utf8: bool = True
    path_b64: str = ""

    #: Valorizzato per ``Status.SKIPPED``: symlink, entry cross-device,
    #: directory illeggibile (§7.3).
    skip_reason: str = ""

    #: Primo pattern che ha escluso l'entry, e l'opzione da cui proviene (§3.4).
    excluded_by: str = ""
    excluded_kind: str = ""

    #: Solo nel manifest: differiscono fra host e sono esclusi dal diff dei
    #: report (§13).
    size: int = 0
    mtime: str = ""

    #: Path assoluto su disco, per le operazioni di rename. Non serializzato:
    #: e' specifico dell'host.
    abs_path: str = field(default="", repr=False)

    @property
    def name(self) -> str:
        """Componente finale del path relativo."""
        i = self.rel_path.rfind("/")
        return self.rel_path[i + 1 :] if i >= 0 else self.rel_path

    @property
    def type(self) -> str:
        """Valore della colonna ``type`` del report."""
        return str(self.kind)


# File di servizio di client e server, saltati incondizionatamente e
# indipendentemente da --exclude (§7.3).
#
# Uno skip di bookkeeping non e' un'esclusione: non viene mai riportato, nemmeno
# con --show-excluded (§2.3).
_BOOKKEEPING_EXACT = frozenset({".nextcloud", "files_versions", "files_trashbin"})
_BOOKKEEPING_PREFIXES = (".sync_", ".owncloudsync.log", ".~lock.", "~$")
_BOOKKEEPING_SUFFIXES = (".part", ".filepart")

#: Marcatore dei rinomini temporanei a due passi (§8.1). Il walk deve saltarli:
#: un'esecuzione interrotta inquinerebbe il report successivo con i propri
#: detriti.
TEMP_PREFIX = ".safepath-"


def is_bookkeeping(name: str) -> bool:
    """Riporta se il nome e' un file di servizio da saltare incondizionatamente,
    temporanei di safepath inclusi."""
    lower = name.lower()

    if lower in _BOOKKEEPING_EXACT:
        return True
    if TEMP_PREFIX in name:
        return True
    if lower.startswith(_BOOKKEEPING_PREFIXES):
        return True
    # .sync_*.db e' coperto dal prefisso .sync_; la variante con suffisso
    # numerico dei log di owncloud dal prefisso corrispondente.
    return lower.endswith(_BOOKKEEPING_SUFFIXES)
