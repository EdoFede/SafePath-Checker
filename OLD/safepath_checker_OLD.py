#!/usr/bin/env python3
"""SafePath-Checker — scansione di path per problemi di portabilita' cross-platform.

Read-only: non rinomina ne' modifica nulla, solo segnala.
Riferimento normativo: FileNaming-Technical.md
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Costanti dei controlli (rif. FileNaming-Technical.md)
# ---------------------------------------------------------------------------

WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

ZERO_WIDTH_CHARS = {
    "​", "‌", "‍", "﻿",
}
BIDI_OVERRIDE_RANGES = [
    (0x202A, 0x202E),
    (0x2066, 0x2069),
]
SOFT_HYPHEN = "­"
NBSP = " "
PUA_RANGE = (0xE000, 0xF8FF)

EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
]

PORTABLE_CHARSET_RE = re.compile(r"^[A-Za-z0-9_\-.\(\)\[\] ]+$")

DEFAULT_SKIP_NAMES = {
    ".DS_Store", "Thumbs.db", "Desktop.ini", "desktop.ini",
    ".Spotlight-V100", ".Trashes", ".fseventsd", ".TemporaryItems",
    "$RECYCLE.BIN", "System Volume Information",
}
DEFAULT_SKIP_DIRS = {
    ".git", ".svn", ".hg", ".bzr",
    "__pycache__", ".idea", ".vscode",
    "node_modules",
}

MAX_NAME_BYTES = 255
MAX_NAME_CHARS_WARN = 255
MAX_PATH_CHARS_ERROR = 260
MAX_PATH_CHARS_WARN = 240
MAX_DEPTH_WARN = 20


# ---------------------------------------------------------------------------
# Modello dati
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Issue:
    path: str
    kind: str               # "file" | "dir"
    rule_id: str            # es. "1.1", "3.1"
    rule_name: str
    severity: str           # "error" | "warning" | "info"
    description: str
    detail: str = ""        # info aggiuntive (es. caratteri trovati)


@dataclass
class ScanStats:
    files_scanned: int = 0
    dirs_scanned: int = 0
    permission_errors: int = 0
    symlinks_skipped: int = 0
    issues_by_severity: dict = field(default_factory=lambda: defaultdict(int))


# ---------------------------------------------------------------------------
# Helper di classificazione caratteri
# ---------------------------------------------------------------------------

def _is_control_char(ch: str) -> bool:
    cp = ord(ch)
    return cp <= 0x1F or cp == 0x7F


def _is_bidi_override(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in BIDI_OVERRIDE_RANGES)


def _is_pua(ch: str) -> bool:
    return PUA_RANGE[0] <= ord(ch) <= PUA_RANGE[1]


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def _format_codepoints(chars: Iterable[str]) -> str:
    seen = []
    for ch in chars:
        token = f"U+{ord(ch):04X}"
        if token not in seen:
            seen.append(token)
    return ", ".join(seen)


# ---------------------------------------------------------------------------
# Controlli sul singolo nome
# ---------------------------------------------------------------------------

def check_name(name: str, full_path: str, kind: str, opts: "Options") -> list[Issue]:
    issues: list[Issue] = []

    # 2.2 nomi speciali POSIX
    if name in {".", ".."}:
        issues.append(Issue(full_path, kind, "2.2", "Nome riservato POSIX",
                            "error", "Il nome '.' o '..' non puo' essere usato come file/cartella."))
        return issues

    # 1.1 caratteri Windows-invalid
    bad = sorted({ch for ch in name if ch in WINDOWS_INVALID_CHARS})
    if bad:
        issues.append(Issue(full_path, kind, "1.1", "Caratteri non validi su Windows",
                            "error",
                            "Caratteri rifiutati dall'API Win32 nel nome.",
                            f"Trovati: {' '.join(bad)}"))

    # 1.2 caratteri di controllo
    ctrl = [ch for ch in name if _is_control_char(ch)]
    if ctrl:
        issues.append(Issue(full_path, kind, "1.2", "Caratteri di controllo",
                            "error",
                            "Codepoint U+0000-U+001F o U+007F presenti nel nome.",
                            f"Codepoint: {_format_codepoints(ctrl)}"))

    # 1.3 zero-width / bidi / nbsp / soft hyphen / PUA
    invisible = []
    for ch in name:
        if ch in ZERO_WIDTH_CHARS or _is_bidi_override(ch) or ch == SOFT_HYPHEN \
                or ch == NBSP or _is_pua(ch):
            invisible.append(ch)
    if invisible:
        issues.append(Issue(full_path, kind, "1.3", "Caratteri Unicode invisibili o ambigui",
                            "warning",
                            "Caratteri zero-width, bidi-override, NBSP, soft-hyphen o PUA.",
                            f"Codepoint: {_format_codepoints(invisible)}"))

    # 1.4 emoji (solo se richiesto)
    if opts.check_emoji:
        emo = [ch for ch in name if _is_emoji(ch)]
        if emo:
            issues.append(Issue(full_path, kind, "1.4", "Emoji o pittogrammi",
                                "warning",
                                "Emoji presenti nel nome (compatibilita' limitata con tool legacy).",
                                f"Codepoint: {_format_codepoints(emo)}"))

    # 2.1 nomi riservati Windows (anche con estensione)
    stem = name.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        issues.append(Issue(full_path, kind, "2.1", "Nome riservato Windows",
                            "error",
                            f"Il nome '{stem}' e' riservato dal sistema Windows.",
                            ""))

    # 3.1 spazio finale
    if name.endswith(" "):
        issues.append(Issue(full_path, kind, "3.1", "Spazio finale",
                            "error",
                            "Windows tronca silenziosamente gli spazi a fine nome.",
                            ""))

    # 3.2 punto finale (esclude nomi puri "." / "..": gia' gestiti)
    if name.endswith(".") and name not in {".", ".."}:
        issues.append(Issue(full_path, kind, "3.2", "Punto finale",
                            "error",
                            "Windows rimuove i punti finali dal nome.",
                            ""))

    # 3.3 spazio iniziale
    if name.startswith(" "):
        issues.append(Issue(full_path, kind, "3.3", "Spazio iniziale",
                            "warning",
                            "Lo spazio iniziale viene spesso troncato da tool e upload form.",
                            ""))

    # 3.4 punto iniziale (info) — escludi puri "." / ".."
    if opts.show_info and name.startswith(".") and name not in {".", ".."}:
        issues.append(Issue(full_path, kind, "3.4", "Punto iniziale",
                            "info",
                            "Convenzione POSIX per file nascosti; su Windows non ha effetto.",
                            ""))

    # 3.5 tilde o dollaro iniziali
    if name.startswith("~") or name.startswith("$"):
        issues.append(Issue(full_path, kind, "3.5", "Prefisso '~' o '$'",
                            "warning",
                            "Convenzione di lock per file temporanei Office/Windows.",
                            ""))

    # 4 normalizzazione Unicode (NFC)
    nfc = unicodedata.normalize("NFC", name)
    if nfc != name:
        form = "NFD" if unicodedata.normalize("NFD", name) == name else "non-NFC"
        issues.append(Issue(full_path, kind, "4", "Forma Unicode non-NFC",
                            "warning",
                            f"Il nome e' memorizzato in forma {form}; atteso NFC.",
                            ""))

    # 5.1 lunghezza nome
    name_bytes = len(name.encode("utf-8", errors="surrogatepass"))
    if name_bytes > MAX_NAME_BYTES:
        issues.append(Issue(full_path, kind, "5.1", "Nome troppo lungo (byte)",
                            "error",
                            f"Nome di {name_bytes} byte UTF-8 (limite {MAX_NAME_BYTES}).",
                            ""))
    elif len(name) > MAX_NAME_CHARS_WARN:
        issues.append(Issue(full_path, kind, "5.1", "Nome troppo lungo (caratteri)",
                            "warning",
                            f"Nome di {len(name)} caratteri (limite consigliato {MAX_NAME_CHARS_WARN}).",
                            ""))

    # 7.2 spazi multipli consecutivi (info)
    if opts.show_info and "  " in name:
        issues.append(Issue(full_path, kind, "7.2", "Spazi multipli consecutivi",
                            "info",
                            "Spazi consecutivi nel nome (possibili residui di copia-incolla).",
                            ""))

    # 9 strict-ASCII / set portabile
    if opts.strict_ascii and not PORTABLE_CHARSET_RE.match(name):
        issues.append(Issue(full_path, kind, "9", "Fuori dal set portabile",
                            "warning",
                            "Il nome contiene caratteri fuori dal set ASCII portabile raccomandato.",
                            ""))

    return issues


def check_full_path(full_path: str, kind: str, opts: "Options",
                    base_for_length: str | None) -> list[Issue]:
    """Controlli sul path nella sua interezza: lunghezza e profondita'."""
    issues: list[Issue] = []

    # 5.2 lunghezza path: se l'utente ha passato base, calcola relativo per simulare
    # come apparirebbe sul sistema di destinazione.
    if base_for_length:
        try:
            rel = os.path.relpath(full_path, base_for_length)
        except ValueError:
            rel = full_path
        length = len(rel)
    else:
        length = len(full_path)

    if length > MAX_PATH_CHARS_ERROR:
        issues.append(Issue(full_path, kind, "5.2", "Path troppo lungo",
                            "error",
                            f"Path di {length} caratteri (limite Windows classico {MAX_PATH_CHARS_ERROR}).",
                            ""))
    elif length > MAX_PATH_CHARS_WARN:
        issues.append(Issue(full_path, kind, "5.2", "Path lungo",
                            "warning",
                            f"Path di {length} caratteri (soglia di attenzione {MAX_PATH_CHARS_WARN}).",
                            ""))

    # 5.3 profondita' (conta i separatori del path relativo se disponibile)
    if base_for_length:
        try:
            rel = os.path.relpath(full_path, base_for_length)
            depth = 0 if rel in {".", ""} else rel.count(os.sep) + 1
        except ValueError:
            depth = full_path.count(os.sep)
    else:
        depth = full_path.count(os.sep)
    if depth > MAX_DEPTH_WARN:
        issues.append(Issue(full_path, kind, "5.3", "Profondita' eccessiva",
                            "warning",
                            f"Annidamento a {depth} livelli (soglia {MAX_DEPTH_WARN}).",
                            ""))

    return issues


def check_case_insensitive_collisions(dir_path: str, entries: list[tuple[str, str]],
                                      issues: list[Issue]) -> None:
    """entries: lista di (name, kind) all'interno della stessa directory."""
    by_lower: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, kind in entries:
        by_lower[name.lower()].append((name, kind))

    for lower_name, group in by_lower.items():
        if len(group) < 2:
            continue
        files_in_group = [g for g in group if g[1] == "file"]
        dirs_in_group = [g for g in group if g[1] == "dir"]
        names_list = ", ".join(sorted({n for n, _ in group}))
        if len(files_in_group) >= 2:
            for name, kind in files_in_group:
                issues.append(Issue(os.path.join(dir_path, name), kind, "6.1",
                                    "Duplicati case-insensitive (file)",
                                    "error",
                                    "Piu' file nello stesso folder differiscono solo per maiuscole/minuscole.",
                                    f"Varianti: {names_list}"))
        if len(dirs_in_group) >= 2:
            for name, kind in dirs_in_group:
                issues.append(Issue(os.path.join(dir_path, name), kind, "6.2",
                                    "Duplicati case-insensitive (directory)",
                                    "warning",
                                    "Piu' cartelle nello stesso folder differiscono solo per maiuscole/minuscole.",
                                    f"Varianti: {names_list}"))


# ---------------------------------------------------------------------------
# Opzioni di scansione
# ---------------------------------------------------------------------------

@dataclass
class Options:
    base_path: str
    base_for_length: str | None
    follow_symlinks: bool = False
    include_hidden: bool = False
    show_info: bool = False
    check_emoji: bool = False
    strict_ascii: bool = False


def should_skip(name: str, kind: str, opts: Options) -> bool:
    if opts.include_hidden:
        return False
    if name in DEFAULT_SKIP_NAMES:
        return True
    if kind == "dir" and name in DEFAULT_SKIP_DIRS:
        return True
    return False


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan(opts: Options) -> tuple[list[Issue], ScanStats]:
    issues: list[Issue] = []
    stats = ScanStats()
    base = opts.base_path

    base_path_obj = Path(base)
    if not base_path_obj.exists():
        print(f"Errore: il percorso '{base}' non esiste.", file=sys.stderr)
        sys.exit(2)
    if not base_path_obj.is_dir():
        print(f"Errore: '{base}' non e' una directory.", file=sys.stderr)
        sys.exit(2)

    for current_dir, dirnames, filenames in os.walk(base, followlinks=opts.follow_symlinks,
                                                    onerror=lambda e: _on_walk_error(e, issues, stats)):
        stats.dirs_scanned += 1

        # filtro hidden in-place per non scendere dentro a quelli skippati
        kept_dirs = []
        for d in dirnames:
            if should_skip(d, "dir", opts):
                continue
            full = os.path.join(current_dir, d)
            if not opts.follow_symlinks and os.path.islink(full):
                stats.symlinks_skipped += 1
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        kept_files = []
        for f in filenames:
            if should_skip(f, "file", opts):
                continue
            full = os.path.join(current_dir, f)
            if not opts.follow_symlinks and os.path.islink(full):
                stats.symlinks_skipped += 1
                continue
            kept_files.append(f)

        # controlli per ogni nome
        dir_entries: list[tuple[str, str]] = []
        for d in kept_dirs:
            full = os.path.join(current_dir, d)
            issues.extend(check_name(d, full, "dir", opts))
            issues.extend(check_full_path(full, "dir", opts, opts.base_for_length))
            dir_entries.append((d, "dir"))

        for f in kept_files:
            full = os.path.join(current_dir, f)
            stats.files_scanned += 1
            issues.extend(check_name(f, full, "file", opts))
            issues.extend(check_full_path(full, "file", opts, opts.base_for_length))
            dir_entries.append((f, "file"))

        check_case_insensitive_collisions(current_dir, dir_entries, issues)

    for iss in issues:
        stats.issues_by_severity[iss.severity] += 1

    return issues, stats


def _on_walk_error(err: OSError, issues: list[Issue], stats: ScanStats) -> None:
    stats.permission_errors += 1
    path = getattr(err, "filename", "") or "?"
    issues.append(Issue(path, "dir", "0.0", "Accesso negato",
                        "warning",
                        "Impossibile leggere la directory; voce saltata.",
                        f"{type(err).__name__}: {err}"))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SEVERITY_LABELS = {
    "error": "ERRORE",
    "warning": "AVVISO",
    "info": "INFO",
}


def filter_and_sort(issues: list[Issue], min_severity: str) -> list[Issue]:
    threshold = SEVERITY_ORDER[min_severity]
    filtered = [i for i in issues if SEVERITY_ORDER[i.severity] <= threshold]
    filtered.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.path, i.rule_id))
    return filtered


def display_path(full_path: str, base_path: str) -> str:
    """Path relativo alla radice scansionata, senza il nome della radice.

    Mostra ad esempio 'sub/file.txt' anziche' il path assoluto.
    Cade su path assoluto se non e' possibile calcolare il relativo.
    """
    try:
        rel = os.path.relpath(full_path, base_path)
    except ValueError:
        return full_path
    if rel == "." or rel.startswith(".."):
        return full_path
    return rel


def print_table(issues: list[Issue], stats: ScanStats, base_path: str,
                stream=sys.stdout) -> None:
    print(f"SafePath-Checker — scansione di: {base_path}", file=stream)
    print(f"Data: {datetime.now().isoformat(timespec='seconds')}", file=stream)
    print(file=stream)
    print(f"File esaminati:        {stats.files_scanned}", file=stream)
    print(f"Cartelle esaminate:    {stats.dirs_scanned}", file=stream)
    print(f"Errori di accesso:     {stats.permission_errors}", file=stream)
    print(f"Symlink saltati:       {stats.symlinks_skipped}", file=stream)
    print(file=stream)
    print(f"Problemi totali:       {len(issues)}", file=stream)
    for sev in ("error", "warning", "info"):
        n = stats.issues_by_severity.get(sev, 0)
        print(f"  {SEVERITY_LABELS[sev]:<8} {n}", file=stream)
    print(file=stream)

    if not issues:
        print("Nessun problema rilevato.", file=stream)
        return

    headers = ["Severita'", "Regola", "Tipo", "Problema", "Path", "Dettaglio"]
    rows = [
        [
            SEVERITY_LABELS[i.severity],
            i.rule_id,
            i.kind,
            i.rule_name,
            display_path(i.path, base_path),
            i.detail,
        ]
        for i in issues
    ]

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    cap = [10, 7, 5, 36, 80, 40]
    widths = [min(w, c) for w, c in zip(widths, cap)]

    def fmt(row: list[str]) -> str:
        cells = []
        for cell, w in zip(row, widths):
            if len(cell) > w:
                cell = cell[: max(0, w - 1)] + "…"
            cells.append(cell.ljust(w))
        return "  ".join(cells)

    sep = "  ".join("-" * w for w in widths)
    print(fmt(headers), file=stream)
    print(sep, file=stream)
    for row in rows:
        print(fmt(row), file=stream)


def write_csv(issues: list[Issue], base_path: str, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["severity", "rule_id", "rule_name", "kind", "path",
                         "description", "detail"])
        for i in issues:
            writer.writerow([i.severity, i.rule_id, i.rule_name, i.kind,
                             display_path(i.path, base_path),
                             i.description, i.detail])


def write_json(issues: list[Issue], stats: ScanStats, base_path: str, path: str) -> None:
    payload = {
        "base_path": base_path,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": {
            "files_scanned": stats.files_scanned,
            "dirs_scanned": stats.dirs_scanned,
            "permission_errors": stats.permission_errors,
            "symlinks_skipped": stats.symlinks_skipped,
            "issues_by_severity": dict(stats.issues_by_severity),
            "total_issues": len(issues),
        },
        "issues": [
            {**asdict(i), "path": display_path(i.path, base_path)}
            for i in issues
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_html(issues: list[Issue], stats: ScanStats, base_path: str, path: str) -> None:
    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    rows_html = []
    for i in issues:
        rows_html.append(
            f"<tr class='sev-{esc(i.severity)}'>"
            f"<td>{esc(SEVERITY_LABELS[i.severity])}</td>"
            f"<td>{esc(i.rule_id)}</td>"
            f"<td>{esc(i.kind)}</td>"
            f"<td>{esc(i.rule_name)}</td>"
            f"<td><code>{esc(display_path(i.path, base_path))}</code></td>"
            f"<td>{esc(i.description)}</td>"
            f"<td>{esc(i.detail)}</td>"
            f"</tr>"
        )

    sev_summary = "".join(
        f"<li><strong>{esc(SEVERITY_LABELS[s])}</strong>: "
        f"{stats.issues_by_severity.get(s, 0)}</li>"
        for s in ("error", "warning", "info")
    )

    doc = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>SafePath-Checker — Report</title>
<style>
body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2em; color: #222; }}
h1 {{ margin-bottom: 0.2em; }}
.meta {{ color: #666; margin-bottom: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; }}
tr.sev-error {{ background: #fdecec; }}
tr.sev-warning {{ background: #fff7e0; }}
tr.sev-info {{ background: #eef4fb; }}
code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }}
.summary li {{ margin: 0.1em 0; }}
</style>
</head>
<body>
<h1>SafePath-Checker — Report</h1>
<p class="meta">Scansione di <code>{esc(base_path)}</code> &mdash;
generato il {esc(datetime.now().isoformat(timespec='seconds'))}</p>
<h2>Riepilogo</h2>
<ul class="summary">
<li>File esaminati: {stats.files_scanned}</li>
<li>Cartelle esaminate: {stats.dirs_scanned}</li>
<li>Errori di accesso: {stats.permission_errors}</li>
<li>Symlink saltati: {stats.symlinks_skipped}</li>
<li>Problemi totali: {len(issues)}</li>
</ul>
<ul class="summary">{sev_summary}</ul>
<h2>Dettaglio problemi</h2>
<table>
<thead><tr>
<th>Severita'</th><th>Regola</th><th>Tipo</th><th>Problema</th>
<th>Path</th><th>Descrizione</th><th>Dettaglio</th>
</tr></thead>
<tbody>
{''.join(rows_html) if rows_html else '<tr><td colspan="7">Nessun problema rilevato.</td></tr>'}
</tbody>
</table>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


# ---------------------------------------------------------------------------
# Email (predisposto, non attivo nella v1)
# ---------------------------------------------------------------------------

def send_email_report(*args, **kwargs) -> None:
    """Predisposto per l'invio del report via email (smtplib).

    Non implementato nella v1: la struttura del report (HTML/CSV/JSON) e' gia'
    pronta per essere allegata. L'implementazione richiedera':
      - lettura config SMTP (host, porta, user, password, from, to) da file/env
      - composizione MIME multipart con allegato del report
      - flag CLI --email / --smtp-config

    Lasciato come stub per non introdurre codice non testato.
    """
    raise NotImplementedError(
        "Invio email non implementato nella v1. Generare il report e inviarlo manualmente."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="safepath-checker",
        description="Analizza i nomi di file e cartelle per problemi di portabilita' "
                    "cross-platform (Windows/macOS/Linux).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("path", help="Percorso da scansionare (directory).")
    p.add_argument("--base-for-length", metavar="PATH",
                   help="Base-path di riferimento per calcolare la lunghezza del path "
                        "come apparira' sul sistema di destinazione. "
                        "Se omesso, usa il path assoluto locale.")
    p.add_argument("--follow-symlinks", action="store_true",
                   help="Segui i symlink (default: no).")
    p.add_argument("--include-hidden", action="store_true",
                   help="Includi file/cartelle di sistema (es. .DS_Store, .git).")
    p.add_argument("--show-info", action="store_true",
                   help="Mostra anche le segnalazioni di severita' 'info'.")
    p.add_argument("--check-emoji", action="store_true",
                   help="Segnala emoji/pittogrammi nei nomi.")
    p.add_argument("--strict-ascii", action="store_true",
                   help="Segnala caratteri fuori dal set ASCII portabile.")
    p.add_argument("--min-severity", choices=["error", "warning", "info"],
                   default="warning",
                   help="Severita' minima da riportare nell'output.")
    p.add_argument("--csv", metavar="FILE", help="Esporta il report in formato CSV.")
    p.add_argument("--json", metavar="FILE", help="Esporta il report in formato JSON.")
    p.add_argument("--html", metavar="FILE", help="Esporta il report in formato HTML.")
    p.add_argument("--quiet", action="store_true",
                   help="Non stampare la tabella a terminale (utile con --csv/--html/--json).")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.show_info and args.min_severity == "warning":
        min_severity = "info"
    else:
        min_severity = args.min_severity

    base_abs = os.path.abspath(args.path)
    base_for_length = (os.path.abspath(args.base_for_length)
                       if args.base_for_length else None)

    opts = Options(
        base_path=base_abs,
        base_for_length=base_for_length,
        follow_symlinks=args.follow_symlinks,
        include_hidden=args.include_hidden,
        show_info=args.show_info,
        check_emoji=args.check_emoji,
        strict_ascii=args.strict_ascii,
    )

    issues, stats = scan(opts)
    visible = filter_and_sort(issues, min_severity)

    if not args.quiet:
        print_table(visible, stats, base_abs)

    if args.csv:
        write_csv(visible, base_abs, args.csv)
        print(f"Report CSV scritto in: {args.csv}", file=sys.stderr)
    if args.json:
        write_json(visible, stats, base_abs, args.json)
        print(f"Report JSON scritto in: {args.json}", file=sys.stderr)
    if args.html:
        write_html(visible, stats, base_abs, args.html)
        print(f"Report HTML scritto in: {args.html}", file=sys.stderr)

    has_errors = stats.issues_by_severity.get("error", 0) > 0
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
