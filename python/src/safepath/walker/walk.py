"""Attraversamento del filesystem e produzione delle entry da validare."""

import base64
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from .. import rules
from .entry import Entry, Status, is_bookkeeping
from .exclude import Matcher
from .osdep import device_id, is_reparse_point, is_symlink, long_path

#: Riceve il listing di una directory e puo' modificarlo prima che il walk
#: prosegua. E' il punto di innesto di auto-rename, che rinomina mentre discende:
#: le entry restituite sostituiscono quelle passate, cosi' che i figli siano
#: scoperti e riportati sotto il nome definitivo del padre (§9.1).
DirHook = Callable[[str, list[Entry]], list[Entry]]


class WalkError(OSError):
    """Errore che rende priva di senso la scansione di una scan root."""


@dataclass
class Options:
    """Configura una scansione."""

    matcher: Matcher | None = None
    dir_hook: DirHook | None = None


def walk(root_arg: str, root: str, opts: Options | None = None) -> list[Entry]:
    """Attraversa ``root`` e restituisce le entry incontrate, ordinate per byte
    order del path NFC (§5).

    ``root_arg`` e' l'argomento verbatim di riga di comando, riportato nella
    colonna ``root``; ``root`` e' il path risolto su disco. La scan root non e'
    validata come componente: solo il suo contenuto (§2.1).
    """
    opts = opts or Options()

    try:
        info = os.lstat(long_path(root))
    except OSError as exc:
        raise WalkError(f"impossibile leggere la scan root {root_arg!r}: {exc}") from exc

    # Un argomento che punta a un singolo file viene validato da solo (§2.1).
    if not _is_dir(info):
        return [_new_entry(root_arg, PurePath(root).name, root, info)]

    try:
        root_dev = device_id(long_path(root))
    except OSError as exc:
        raise WalkError(f"impossibile identificare il device di {root_arg!r}: {exc}") from exc

    state = _Walk(root_arg=root_arg, dev=root_dev, opts=opts)
    state.descend(root, "")

    state.entries.sort(key=lambda e: e.rel_path)
    return state.entries


@dataclass
class _Walk:
    """Stato di una singola scansione."""

    root_arg: str
    dev: int
    opts: Options
    entries: list[Entry] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.entries = []

    def descend(self, dir_abs: str, dir_rel: str) -> None:
        """Elabora una directory per volta, completandola prima di scendere,
        come richiede il ciclo per-directory di §9.1."""
        try:
            names = os.listdir(long_path(dir_abs))
        except OSError as exc:
            # Una directory illeggibile e' una riga skipped e il walk prosegue:
            # un errore di permessi non interrompe l'esecuzione (§7.3).
            self.entries.append(
                Entry(
                    root=self.root_arg,
                    rel_path=_normalize_rel(dir_rel),
                    kind=rules.Kind.DIR,
                    status=Status.SKIPPED,
                    skip_reason=f"directory illeggibile: {exc}",
                    valid_utf8=_is_valid_utf8(dir_rel),
                    abs_path=dir_abs,
                )
            )
            return

        # L'ordine di listdir differisce fra ext4, NTFS e APFS: ordinare ogni
        # listing e' cio' che rende deterministico anche l'ordine dei rename,
        # non solo quello del report (§7.3).
        names.sort(key=rules.to_nfc)

        listing: list[Entry] = []
        for name in names:
            if is_bookkeeping(name):
                continue  # mai riportato, nemmeno con --show-excluded (§2.3)

            abs_path = os.path.join(dir_abs, name)
            try:
                info = os.lstat(long_path(abs_path))
            except OSError as exc:
                listing.append(
                    self._skipped(
                        name, abs_path, rules.Kind.FILE, f"impossibile leggere l'entry: {exc}"
                    )
                )
                continue

            skipped = self._check_traversable(name, abs_path, info)
            if skipped is not None:
                listing.append(skipped)
                continue

            listing.append(_new_entry(self.root_arg, name, abs_path, info))

        # Il path relativo va completato prima dell'hook: auto-rename ragiona su
        # path relativi alla root, non su nomi isolati.
        for e in listing:
            e.rel_path = _normalize_rel(_join_rel(dir_rel, e.rel_path))

        listing = self._apply_exclusions(listing)

        if self.opts.dir_hook is not None:
            listing = self.opts.dir_hook(dir_abs, listing)

        self.entries.extend(listing)

        # La discesa avviene dopo l'hook, sotto i nomi definitivi: nessun path
        # registrato in precedenza diventa obsoleto (§9.1).
        for e in listing:
            if e.kind is not rules.Kind.DIR or e.status in (Status.SKIPPED, Status.EXCLUDED):
                continue
            self.descend(e.abs_path, e.rel_path)

    def _check_traversable(self, name: str, abs_path: str, info: os.stat_result) -> Entry | None:
        """Applica le regole di traversal di §7.3: symlink e reparse point non
        vengono seguiti, i confini di filesystem non vengono attraversati."""
        kind = rules.Kind.DIR if _is_dir(info) else rules.Kind.FILE

        # Seguire i symlink romperebbe il conteggio della profondita' e puo'
        # produrre cicli.
        if is_symlink(info):
            return self._skipped(name, abs_path, kind, "symlink non attraversato")
        if is_reparse_point(info):
            return self._skipped(name, abs_path, kind, "reparse point non attraversato")

        if _is_dir(info):
            try:
                dev = device_id(long_path(abs_path))
            except OSError as exc:
                return self._skipped(
                    name, abs_path, kind, f"impossibile identificare il device: {exc}"
                )
            if dev != self.dev:
                return self._skipped(name, abs_path, kind, "confine di filesystem non attraversato")
        return None

    def _skipped(self, name: str, abs_path: str, kind: rules.Kind, reason: str) -> Entry:
        """Costruisce una riga skipped.

        Il ``rel_path`` e' ancora il solo nome: viene completato dal chiamante.
        """
        return Entry(
            root=self.root_arg,
            rel_path=name,
            kind=kind,
            status=Status.SKIPPED,
            skip_reason=reason,
            valid_utf8=_is_valid_utf8(name),
            abs_path=abs_path,
        )

    def _apply_exclusions(self, listing: list[Entry]) -> list[Entry]:
        """Marca le entry che corrispondono ai pattern utente.

        Una directory esclusa esclude l'intero sottoalbero, che non viene
        proprio percorso: e' cio' che rende ``--exclude 'node_modules'``
        economico e non solo silenzioso (§2.3).
        """
        if self.opts.matcher is None:
            return listing

        for e in listing:
            if e.status is Status.SKIPPED:
                continue
            p = self.opts.matcher.match(e.name, e.rel_path)
            if p is not None:
                e.status = Status.EXCLUDED
                e.excluded_by = p.raw
                e.excluded_kind = p.kind
        return listing


def _new_entry(root_arg: str, name: str, abs_path: str, info: os.stat_result) -> Entry:
    """Costruisce un'entry a partire dal nome su disco."""
    kind = rules.Kind.DIR if _is_dir(info) else rules.Kind.FILE
    valid = _is_valid_utf8(name)

    e = Entry(
        root=root_arg,
        rel_path=name,
        kind=kind,
        valid_utf8=valid,
        # Registrato prima di qualsiasi conversione: e' l'informazione che
        # CHR-002 rende visibile (§6.3).
        nfc_normalized=rules.is_nfc(name) if valid else False,
        size=info.st_size,
        mtime=datetime.fromtimestamp(info.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        abs_path=abs_path,
    )
    if not valid:
        e.path_b64 = base64.b64encode(_raw_bytes(name)).decode("ascii")
    return e


def _is_dir(info: os.stat_result) -> bool:
    """Riporta se lo stat descrive una directory, senza seguire i symlink."""
    return stat.S_ISDIR(info.st_mode)


def _is_valid_utf8(name: str) -> bool:
    """Riporta se il nome e' decodificabile come UTF-8.

    ``os.listdir`` restituisce ``str`` con ``surrogateescape``: i byte non
    decodificabili diventano surrogati isolati, che non sono serializzabili in
    JSON (§7.1).
    """
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _raw_bytes(name: str) -> bytes:
    """Restituisce i byte grezzi di un nome non decodificabile (§7.1)."""
    return name.encode("utf-8", "surrogateescape")


def _join_rel(dir_rel: str, name: str) -> str:
    """Concatena il path relativo della directory con il nome di un'entry."""
    return f"{dir_rel}/{name}" if dir_rel else name


def _normalize_rel(p: str) -> str:
    """Porta un path relativo nella forma dei report: NFC, separatori "/",
    nessun "./" iniziale (§5)."""
    p = p.replace(os.sep, "/")
    p = p.removeprefix("./")
    return rules.to_nfc(p)
