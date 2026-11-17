"""Esecuzione dei due sottocomandi."""

from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from .. import rename, report, rules, walker
from ..version import VERSION
from .options import (
    EXIT_DRIFT,
    EXIT_IO,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VIOLATION,
    USAGE,
    Options,
    UsageError,
    parse,
)


def run(args: list[str], stdout: TextIO, stderr: TextIO) -> int:
    """Esegue il comando e restituisce l'exit code.

    ``stdout`` riceve la tabella e il riepilogo; ``stderr`` diagnostica ed
    errori, cosi' che una redirezione catturi la sola tabella (§4.1).
    """
    try:
        opts = parse(args)
    except UsageError as exc:
        stderr.write(f"safepath: {exc}\n")
        stderr.write(USAGE)
        return EXIT_USAGE

    try:
        matcher = walker.Matcher(opts.exclude, opts.exclude_regex)
    except walker.PatternError as exc:
        # Un pattern non compilabile non viene mai trattato come stringa
        # letterale: e' exit 2 con il messaggio del compilatore (§2.3).
        stderr.write(f"safepath: {exc}\n")
        return EXIT_USAGE

    rep = _new_report(opts)

    executor: rename.Executor | None = None
    journal: rename.Journal | None = None
    if opts.command == "auto-rename":
        try:
            journal = rename.Journal(opts.journal) if opts.journal else None
            executor = _prepare_rename(opts, journal, stderr)
        except OSError as exc:
            stderr.write(f"safepath: {exc}\n")
            return EXIT_IO

    try:
        all_entries: list[walker.Entry] = []
        for p in opts.paths:
            try:
                all_entries.extend(_scan_root(p, matcher, executor))
            except walker.WalkError as exc:
                # Una scan root illeggibile rende l'esecuzione priva di senso:
                # e' uno dei pochi errori che interrompono (§9.4).
                stderr.write(f"safepath: {exc}\n")
                return EXIT_USAGE

        _build_rows(rep, all_entries, executor)
        rep.sort()

        try:
            _emit(rep, all_entries, opts, stdout)
        except OSError as exc:
            stderr.write(f"safepath: {exc}\n")
            return EXIT_IO
    finally:
        if journal is not None:
            journal.close()

    return _exit_code(rep, executor)


def _new_report(o: Options) -> report.Report:
    """Prepara l'intestazione, che e' cio' che rende un report riproducibile a
    distanza di mesi (§4.3)."""
    return report.Report(
        schema_version=report.SCHEMA_VERSION,
        ruleset_version=rules.RULESET_VERSION,
        unicode_version=rules.UNICODE_VERSION,
        tool_version=VERSION,
        command=o.command,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        roots=list(o.paths),
        with_actions=o.command == "auto-rename",
        options=report.Options(
            show_ok=o.show_ok,
            show_excluded=o.show_excluded,
            exclude=list(o.exclude),
            exclude_regex=list(o.exclude_regex),
        ),
    )


def _prepare_rename(o: Options, journal: rename.Journal | None, stderr: TextIO) -> rename.Executor:
    """Costruisce l'executor e recupera i temporanei rimasti da un'esecuzione
    interrotta (§8.1, §9.4)."""
    for p in o.paths:
        for orphan in rename.find_orphans(p):
            try:
                rename.recover_orphan(orphan)
            except OSError as exc:
                stderr.write(f"safepath: recupero non riuscito: {exc}\n")
                continue
            stderr.write(
                f"safepath: completato il temporaneo {orphan.name!r} -> {orphan.target!r}\n"
            )

    return rename.Executor(rename.FSRenamer(), journal)


def _scan_root(
    root_arg: str, matcher: walker.Matcher, ex: rename.Executor | None
) -> list[walker.Entry]:
    """Esegue il walk di una singola scan root."""
    abs_path = str(Path(root_arg).absolute())
    opts = walker.Options(
        matcher=matcher if matcher else None,
        dir_hook=ex.process_dir if ex is not None else None,
    )
    return walker.walk(root_arg, abs_path, opts)


def _build_rows(
    rep: report.Report, entries: list[walker.Entry], ex: rename.Executor | None
) -> None:
    """Trasforma le entry in righe di report, applicando la validazione e, per
    auto-rename, gli esiti delle rinomine."""
    # Le collisioni si valutano per directory: nomi in directory diverse non
    # competono (§5).
    collisions = _collisions_by_dir(entries)

    for e in entries:
        rep.summary.examined += 1
        row = report.Row(root=e.root, path=e.rel_path, type=e.type, status="")

        if e.status is walker.Status.SKIPPED:
            # Cio' che il tool non ha potuto esaminare e' un finding: le righe
            # skipped sono sempre emesse, indipendentemente da --show-ok (§3.3).
            row.status = str(walker.Status.SKIPPED)
            row.detail = e.skip_reason
            rep.summary.skipped += 1

        elif e.status is walker.Status.EXCLUDED:
            row.status = str(walker.Status.EXCLUDED)
            row.detail = e.excluded_kind
            row.excluded_by = e.excluded_by
            rep.summary.excluded += 1
            if not rep.options.show_excluded:
                continue  # nessuna riga senza il flag (§3.4)

        else:
            # La validazione avviene sul path com'era prima della rinomina:
            # codes descrive sempre lo stato originale, anche a rinomina
            # riuscita. Un report i cui findings si svuotassero come effetto
            # collaterale della correzione sarebbe inutile come traccia di
            # audit; per vedere l'albero dopo la remediation si riesegue scan,
            # che e' esattamente a questo che serve (§3.2).
            # L'executor indicizza ogni esito anche sotto il path definitivo,
            # perche' il walk restituisce le entry gia' rinominate: e' da li'
            # che si recupera il path originale su cui validare.
            validated = e.rel_path
            res = ex.results.get(e.rel_path) if ex is not None else None
            if res is not None and res.rel_path:
                validated = res.rel_path
            row.path = validated

            codes = rules.validate_path(
                rules.Target(rel_path=validated, kind=e.kind, valid_utf8=e.valid_utf8)
            )
            if e.rel_path in collisions and rules.UNQ_001 not in codes:
                codes = sorted([*codes, rules.UNQ_001])

            row.codes = codes
            if not codes:
                row.status = str(walker.Status.OK)
                rep.summary.ok += 1
            else:
                row.status = str(walker.Status.VIOLATION)
                row.detail = rules.describe_codes(codes)
                rep.summary.violations += 1

            # I conteggi delle azioni precedono lo scarto delle righe ok:
            # --show-ok cambia quali righe sono emesse e nient'altro, non il
            # riepilogo ne' l'exit code (§3.3).
            if rep.with_actions:
                _apply_action(row, e, ex, rep)
            if not codes and not rep.options.show_ok:
                continue  # solo le righe non ok, per default (§3.3)
            rep.rows.append(row)
            continue

        if rep.with_actions:
            _apply_action(row, e, ex, rep)
        rep.rows.append(row)

    if ex is not None and not ex.unmapped.empty():
        rep.unmapped = ex.unmapped.chars()


def _apply_action(
    row: report.Row,
    e: walker.Entry,
    ex: rename.Executor | None,
    rep: report.Report,
) -> None:
    """Riempie le colonne azione di una riga (§3.2).

    I codici continuano a descrivere lo stato originale anche a rinomina
    riuscita: il report documenta cio' che e' stato trovato, non cio' che resta.
    """
    if ex is None:
        return

    res = ex.results.get(e.rel_path)
    if res is None:
        row.action = report.Action.NONE
        row.outcome = report.Outcome.UNCHANGED
        row.outcome_detail = "nessuna azione necessaria"
        return

    row.action = report.Action(res.action)
    row.new_path = res.new_path
    row.outcome = report.Outcome(res.outcome)
    row.outcome_detail = res.detail

    if res.action == rename.ACTION_RENAME and res.outcome == "ok":
        rep.summary.renamed += 1
    elif res.action == rename.ACTION_MANUAL:
        rep.summary.manual += 1
    elif res.outcome == "error":
        rep.summary.failed += 1


def _collisions_by_dir(entries: list[walker.Entry]) -> set[str]:
    """Individua le entry coinvolte in una collisione case-insensitive,
    confrontando solo nomi della stessa directory (§5)."""
    by_dir: dict[tuple[str, str], list[walker.Entry]] = {}
    for e in entries:
        if e.status in (walker.Status.SKIPPED, walker.Status.EXCLUDED):
            continue
        by_dir.setdefault((e.root, _dir_of(e.rel_path)), []).append(e)

    out: set[str] = set()
    for group in by_dir.values():
        colliding = rules.check_collisions([e.name for e in group])
        out.update(e.rel_path for e in group if e.name in colliding)
    return out


def _dir_of(rel_path: str) -> str:
    """Restituisce la porzione di directory di un path relativo."""
    i = rel_path.rfind("/")
    return rel_path[:i] if i >= 0 else ""


def _emit(rep: report.Report, entries: list[walker.Entry], o: Options, stdout: TextIO) -> None:
    """Produce la tabella su stdout e i file richiesti.

    La tabella e' sempre prodotta e nessun output su file la sopprime (§4).
    """
    console_opts = report.detect_console_options(stdout)
    report.write_console(stdout, rep, console_opts)

    if o.output_csv:
        report.write_csv(o.output_csv, rep)
    if o.output_json:
        report.write_json(o.output_json, rep)
    if o.emit_manifest:
        report.write_manifest(o.emit_manifest, entries)


def _exit_code(rep: report.Report, ex: rename.Executor | None) -> int:
    """Determina l'exit code finale (§12).

    L'asimmetria su exit 1 e' voluta: scan riporta cio' che non va, quindi una
    qualsiasi violazione e' exit 1; auto-rename e' fatto per correggere, quindi
    un'esecuzione che ha riparato tutto esce 0. Exit 4 prevale su exit 1, perche'
    la deriva significa che il tool non puo' garantire cio' che ha fatto.
    """
    if ex is not None and ex.drift:
        return EXIT_DRIFT

    if rep.with_actions:
        return EXIT_VIOLATION if rep.has_blocking() else EXIT_OK

    return EXIT_VIOLATION if rep.summary.violations > 0 else EXIT_OK
