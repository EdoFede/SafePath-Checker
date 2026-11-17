"""Serializzazione del report nei formati su file: CSV, JSON e manifest."""

import csv
import io
import json
from pathlib import Path
from typing import Any

from ..walker import Entry, Status
from .model import Report, Row

#: Richiesto da Excel: senza, UTF-8 viene letto come codepage ANSI di sistema e
#: ogni nome accentato viene storpiato — esattamente i nomi che questo tool
#: esiste per trovare (§4.2).
UTF8_BOM = b"\xef\xbb\xbf"


def write_csv(path: str, r: Report) -> None:
    """Scrive il report in CSV secondo RFC 4180 (§4.2).

    BOM e CRLF sono proprieta' del solo writer CSV e non devono raggiungere JSON,
    manifest o console. Il file e' scritto in modalita' binaria con il fine riga
    applicato esplicitamente, mai lasciato alla piattaforma (§5).
    """
    buf = io.StringIO(newline="")
    # QUOTE_MINIMAL quota solo i campi che contengono separatore, virgolette o
    # fine riga, ed escapa le virgolette raddoppiandole, come richiede §4.2.
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    w.writerow(_csv_header(r))
    for row in r.rows:
        w.writerow(_csv_row(row, r))

    Path(path).write_bytes(UTF8_BOM + buf.getvalue().encode("utf-8"))


def _csv_header(r: Report) -> list[str]:
    """Costruisce l'intestazione.

    Il set di colonne non varia con i dati: --show-ok aggiunge righe, mai
    colonne. ``excluded_by`` e' l'unica eccezione ed e' appesa in fondo, cosi'
    che il prefisso resti stabile per un consumatore che legge le colonne per
    posizione (§4.2).
    """
    h = ["root", "path", "type", "status", "codes", "detail"]
    if r.with_actions:
        h += ["action", "new_path", "outcome", "outcome_detail"]
    if r.options.show_excluded:
        h.append("excluded_by")
    return h


def _csv_row(row: Row, r: Report) -> list[str]:
    """Serializza una riga.

    I valori vuoti restano campi vuoti, mai "NULL" o "-", e i codici multipli
    sono separati da spazio dentro un solo campo.
    """
    out = [row.root, row.path, row.type, row.status, " ".join(row.codes), row.detail]
    if r.with_actions:
        out += [
            str(row.action) if row.action else "",
            row.new_path,
            str(row.outcome) if row.outcome else "",
            row.outcome_detail,
        ]
    if r.options.show_excluded:
        out.append(row.excluded_by)
    return out


def write_json(path: str, r: Report) -> None:
    """Scrive il report come singolo documento JSON (§4.3).

    UTF-8 senza BOM, fine riga "\\n", chiavi ordinate. I non-ASCII non vengono
    escapati: i nomi accentati devono restare leggibili nel file.
    """
    doc: dict[str, Any] = {
        "schema_version": r.schema_version,
        "ruleset_version": r.ruleset_version,
        "unicode_version": r.unicode_version,
        "tool_version": r.tool_version,
        "command": r.command,
        "generated_at": r.generated_at,
        "roots": r.roots,
        "options": {
            "show_ok": r.options.show_ok,
            "show_excluded": r.options.show_excluded,
            # Le esclusioni sono riportate come date da riga di comando, non
            # normalizzate, ciascuna nel proprio array: un glob e una regex che
            # si somigliano non significano la stessa cosa (§4.3).
            "exclude": list(r.options.exclude),
            "exclude_regex": list(r.options.exclude_regex),
        },
        "summary": _json_summary(r),
        "entries": _json_entries(r),
    }

    # I caratteri non mappati sono un'informazione operativa: senza, l'utente non
    # sa quali righe aggiungere a CHAR_MAP per rendere automatiche le entry
    # rimaste manual.
    if r.unmapped:
        doc["unmapped_chars"] = [
            {"char": ch, "codepoint": f"U+{ord(ch):04X}", "occurrences": n} for ch, n in r.unmapped
        ]

    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    Path(path).write_bytes(text.encode("utf-8"))


def _json_summary(r: Report) -> dict[str, int]:
    """Serializza il riepilogo; i conteggi delle azioni solo per auto-rename."""
    s = r.summary
    m = {
        "examined": s.examined,
        "ok": s.ok,
        "violations": s.violations,
        "skipped": s.skipped,
        "excluded": s.excluded,
    }
    if r.with_actions:
        m |= {"renamed": s.renamed, "failed": s.failed, "manual": s.manual}
    return m


def _json_entries(r: Report) -> list[dict[str, Any]]:
    """Costruisce l'array delle entry, sempre presente anche se vuoto (§4.3)."""
    out: list[dict[str, Any]] = []

    for row in r.rows:
        e: dict[str, Any] = {
            "root": row.root,
            "path": row.path,
            "type": row.type,
            "status": row.status,
            # codes e' un array, non una stringa: questo e' il formato per le
            # macchine, e l'appiattimento del CSV e' una concessione a un formato
            # testuale, non il modello (§4.3).
            "codes": list(row.codes),
            "detail": row.detail,
        }

        # I quattro campi azione esistono solo per auto-rename: assenti, non
        # nulli, sotto scan.
        if r.with_actions:
            e["action"] = str(row.action) if row.action else ""
            e["new_path"] = row.new_path
            e["outcome"] = str(row.outcome) if row.outcome else ""
            e["outcome_detail"] = row.outcome_detail

        # excluded_by solo sulle righe escluse e solo con --show-excluded.
        if r.options.show_excluded and row.status == "excluded" and row.excluded_by:
            e["excluded_by"] = row.excluded_by

        out.append(e)
    return out


def write_manifest(path: str, entries: list[Entry]) -> None:
    """Scrive la serializzazione JSONL delle entry (§1).

    Il manifest e' un output opzionale e non fa parte del flusso normale: serve
    ad archiviare lo stato a cui un report si riferisce, a fare il diff fra due
    esecuzioni consecutive, ed e' il trasporto usato dai test di parita' (§10).

    Resta JSONL, non un documento unico come il report JSON: e' uno stream.
    """
    buf = io.StringIO()
    for e in entries:
        # L'ordine delle chiavi e' quello dei campi della struct Go e non
        # alfabetico: il manifest e' confrontato byte per byte dai test di
        # parita' (§10), quindi le due implementazioni devono emettere la stessa
        # sequenza. E' l'unico output dove l'ordine non e' quello ordinato di §5.
        obj: dict[str, Any] = {
            "root": e.root,
            "path": e.rel_path,
            "type": e.type,
            # Lo stato e' quello che il walker ha assegnato: la validazione
            # avviene dopo, quindi un'entry non ancora giudicata resta vuota,
            # come nel manifest Go.
            "status": _manifest_status(e),
        }
        obj["nfc_normalized"] = e.nfc_normalized
        obj["valid_utf8"] = e.valid_utf8
        if e.path_b64:
            obj["path_b64"] = e.path_b64
        if e.skip_reason:
            obj["skip_reason"] = e.skip_reason
        if e.excluded_by:
            obj["excluded_by"] = e.excluded_by
        obj["size"] = e.size
        obj["mtime"] = e.mtime

        # separators compatti come l'encoder Go, che non inserisce spazi.
        buf.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        # Fine riga esplicito: mai lasciato alla piattaforma, il file va scritto
        # in modalita' binaria (§5).
        buf.write("\n")

    Path(path).write_bytes(buf.getvalue().encode("utf-8"))


def _manifest_status(e: Entry) -> str:
    """Stato dell'entry nel manifest.

    Il walker marca solo ``skipped`` ed ``excluded``: ``ok`` e ``violation``
    sono conclusioni della validazione, che il manifest precede. Un'entry non
    ancora giudicata ha quindi stato vuoto.
    """
    return str(e.status) if e.status in (Status.SKIPPED, Status.EXCLUDED) else ""
