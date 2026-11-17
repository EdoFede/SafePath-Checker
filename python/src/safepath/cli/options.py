"""Parsing degli argomenti di riga di comando."""

from dataclasses import dataclass, field
from pathlib import Path

# Exit code (Development guidelines §12).
#
# Le violazioni sono dati, non errori: exit 1 deve restare distinguibile da un
# crash perche' il tool sia scriptabile.
EXIT_OK = 0  # esecuzione completata, nulla da correggere
EXIT_VIOLATION = 1  # violazioni trovate (scan) o rimaste (auto-rename)
EXIT_USAGE = 2  # argomenti non validi o path inutilizzabile
EXIT_IO = 3  # errore di I/O nel walk o nella scrittura di un output
EXIT_DRIFT = 4  # una directory e' cambiata sotto il tool (§9.2)

COMMANDS = ("scan", "auto-rename")


class UsageError(Exception):
    """Errore di riga di comando, che vale exit 2."""


@dataclass
class Options:
    """Opzioni di invocazione."""

    command: str  # "scan" | "auto-rename"
    paths: list[str] = field(default_factory=list)  # nell'ordine dato

    show_ok: bool = False
    show_excluded: bool = False
    exclude: list[str] = field(default_factory=list)
    exclude_regex: list[str] = field(default_factory=list)

    output_csv: str = ""
    output_json: str = ""
    emit_manifest: str = ""

    #: Path del journal delle rinomine (§9.4). Vuoto significa nessun journal: il
    #: file non viene creato di default, perche' un output non richiesto nella
    #: directory di lavoro e' una sorpresa, non una funzionalita'. Va archiviato
    #: insieme al report.
    journal: str = ""


def parse(args: list[str]) -> Options:
    """Interpreta gli argomenti di riga di comando.

    Una seconda occorrenza della stessa opzione di output e' rifiutata con exit 2
    invece di prendere silenziosamente l'ultima: un
    ``--output-csv a.csv --output-csv b.csv`` da script e' un bug del chiamante,
    non una preferenza (§2.2). Le esclusioni sono ripetibili per progetto, e un
    flag booleano ripetuto e' innocuo.
    """
    if not args:
        raise UsageError("nessun comando specificato")

    command = args[0]
    if command not in COMMANDS:
        raise UsageError(f"comando sconosciuto {command!r}: usare scan o auto-rename")

    o = Options(command=command)
    seen: set[str] = set()

    def single(name: str) -> None:
        """Rifiuta la seconda occorrenza di un'opzione a occorrenza singola."""
        if name in seen:
            raise UsageError(f"l'opzione {name} e' stata indicata piu' volte")
        seen.add(name)

    rest = args[1:]
    i = 0
    while i < len(rest):
        arg = rest[i]

        # Un "--" isolato termina le opzioni: cio' che segue e' un path anche se
        # inizia con un trattino.
        if arg == "--":
            o.paths.extend(rest[i + 1 :])
            break

        if not arg.startswith("--"):
            o.paths.append(arg)
            i += 1
            continue

        name, sep, inline = arg.partition("=")

        def value(name: str = name, sep: str = sep, inline: str = inline) -> str:
            """Legge il valore dell'opzione, in forma "--opt=val" o "--opt val"."""
            nonlocal i
            if sep:
                return inline
            if i + 1 >= len(rest):
                raise UsageError(f"l'opzione {name} richiede un valore")
            i += 1
            return rest[i]

        match name:
            case "--show-ok":
                o.show_ok = True
            case "--show-excluded":
                o.show_excluded = True
            case "--exclude":
                o.exclude.append(value())
            case "--exclude-regex":
                o.exclude_regex.append(value())
            case "--output-csv":
                v = value()
                single(name)
                o.output_csv = v
            case "--output-json":
                v = value()
                single(name)
                o.output_json = v
            case "--emit-manifest":
                v = value()
                single(name)
                o.emit_manifest = v
            case "--journal":
                v = value()
                single(name)
                o.journal = v
            case _:
                raise UsageError(f"opzione sconosciuta {name}")

        i += 1

    if not o.paths:
        raise UsageError("nessun path indicato: serve almeno un argomento")
    if o.journal and o.command != "auto-rename":
        raise UsageError("--journal si applica solo ad auto-rename: scan non scrive mai")

    _check_paths(o.paths)
    return o


def _check_paths(paths: list[str]) -> None:
    """Rifiuta argomenti ripetuti o annidati.

    Vanno rilevati prima del walk e rifiutati con exit 2 invece di produrre righe
    duplicate: "a" e "a/b" descriverebbero due volte lo stesso sottoalbero, con
    due root diverse e conteggi di profondita' incoerenti (§2.1).
    """
    resolved: list[Path] = []
    for p in paths:
        try:
            resolved.append(Path(p).absolute())
        except OSError as exc:
            raise UsageError(f"path non utilizzabile {p!r}: {exc}") from exc

    for i, a in enumerate(resolved):
        for j, b in enumerate(resolved):
            if i == j:
                continue
            if a == b and i < j:
                raise UsageError(f"il path {paths[i]!r} e' indicato piu' volte")
            if _is_subpath(a, b):
                raise UsageError(
                    f"il path {paths[j]!r} e' contenuto in {paths[i]!r}: "
                    "gli argomenti non possono annidarsi"
                )


def _is_subpath(parent: Path, child: Path) -> bool:
    """Riporta se ``child`` sta sotto ``parent``."""
    if parent == child:
        return False
    return parent in child.parents


USAGE = """
Uso:
  safepath scan        [opzioni] <path>...
  safepath auto-rename [opzioni] <path>...

scan e' in sola lettura ed e' il dry run di auto-rename.

Opzioni:
  --show-ok                include nel report anche le voci conformi
  --exclude <glob>         esclude le voci che corrispondono al glob (ripetibile)
  --exclude-regex <re>     esclude le voci che corrispondono alla regex (ripetibile)
  --show-excluded          include nel report le voci escluse
  --output-csv <file>      scrive il report in CSV
  --output-json <file>     scrive il report in JSON
  --emit-manifest <file>   scrive il manifest JSONL delle voci
  --journal <file>         (solo auto-rename) registra le rinomine eseguite

Exit code:
  0 nulla da correggere   1 violazioni   2 argomenti non validi
  3 errore di I/O         4 deriva rilevata durante l'esecuzione
"""
