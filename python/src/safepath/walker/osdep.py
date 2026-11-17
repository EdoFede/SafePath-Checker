"""Dettagli dipendenti dal sistema operativo.

Tutta la divergenza fra sistemi e' confinata nel package ``walker``: ``rules`` e
``planner`` non accedono al filesystem (Development guidelines §1).
"""

import os
import stat
import sys

#: Attributo NTFS che marca un reparse point (junction, symlink, placeholder di
#: OneDrive). Assente su Unix.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def device_id(path: str) -> int:
    """Identificatore del filesystem che contiene ``path``.

    Serve a non attraversare i confini di mount (§7.3). Su Windows ``st_dev``
    corrisponde al numero di serie del volume.
    """
    return os.lstat(path).st_dev


def is_reparse_point(st: os.stat_result) -> bool:
    """Riporta se l'entry e' un reparse point Windows.

    Sempre falso su Unix, dove il concetto non esiste: i symlink sono gia'
    gestiti a parte.
    """
    if sys.platform != "win32":
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def is_symlink(st: os.stat_result) -> bool:
    """Riporta se l'entry e' un symlink, che non va seguito (§7.3)."""
    return stat.S_ISLNK(st.st_mode)


def long_path(path: str) -> str:
    """Applica il prefisso "\\\\?\\" sui path assoluti Windows (§7.2).

    A differenza di Go, Python non lo applica da solo: il walker puo' attraversare
    alberi pre-remediation che superano MAX_PATH. La forma richiede backslash, un
    path assoluto e nessun "." o "..", quindi si normalizza prima di prefissare.

    Su macOS e Linux il path resta invariato: PATH_MAX e' 1024 byte e non e'
    aggirabile.
    """
    if sys.platform != "win32":
        return path
    if path.startswith("\\\\?\\"):
        return path
    resolved = os.path.abspath(path)
    if resolved.startswith("\\\\"):
        # Percorso UNC: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved
