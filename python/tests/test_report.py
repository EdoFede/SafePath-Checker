"""Test dei formati di output: CSV, JSON, manifest e console."""

import io
import json
from pathlib import Path

from safepath import report, rules, walker


def _report(**kw: object) -> report.Report:
    """Costruisce un report minimo con l'intestazione valorizzata."""
    base = {
        "schema_version": report.SCHEMA_VERSION,
        "ruleset_version": rules.RULESET_VERSION,
        "unicode_version": rules.UNICODE_VERSION,
        "tool_version": "dev",
        "command": "scan",
        "generated_at": "2026-08-07T09:14:22Z",
        "roots": ["10 Amministrazione"],
    }
    return report.Report(**{**base, **kw})  # type: ignore[arg-type]


def _row(**kw: object) -> report.Row:
    base = {
        "root": "10 Amministrazione",
        "path": "Verbali/nota.pdf",
        "type": "file",
        "status": "violation",
    }
    return report.Row(**{**base, **kw})  # type: ignore[arg-type]


class TestCSV:
    """RFC 4180, con le due deroghe deliberate di §4.2."""

    def test_bom_and_crlf(self, tmp_path: Path) -> None:
        """BOM e CRLF sono richiesti dal writer CSV e solo da quello."""
        r = _report()
        r.rows = [_row(codes=["POS-008"], detail="punti consecutivi")]
        out = tmp_path / "r.csv"
        report.write_csv(str(out), r)

        raw = out.read_bytes()
        assert raw.startswith(report.UTF8_BOM)
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")

    def test_codes_are_space_separated(self, tmp_path: Path) -> None:
        """I codici multipli stanno in un solo campo, separati da spazio."""
        r = _report()
        r.rows = [_row(codes=["POS-001", "RSV-002"])]
        out = tmp_path / "r.csv"
        report.write_csv(str(out), r)

        assert "POS-001 RSV-002" in out.read_bytes().decode("utf-8-sig")

    def test_column_set_does_not_vary_with_show_ok(self, tmp_path: Path) -> None:
        """--show-ok aggiunge righe, mai colonne (§4.2)."""
        a, b = tmp_path / "a.csv", tmp_path / "b.csv"
        report.write_csv(str(a), _report())
        report.write_csv(str(b), _report(options=report.Options(show_ok=True)))

        head = lambda p: p.read_bytes().decode("utf-8-sig").splitlines()[0]  # noqa: E731
        assert head(a) == head(b)

    def test_excluded_by_is_appended_last(self, tmp_path: Path) -> None:
        """``excluded_by`` e' appesa in fondo, cosi' che il prefisso resti
        stabile per un consumatore che legge le colonne per posizione."""
        r = _report(options=report.Options(show_excluded=True), with_actions=True)
        out = tmp_path / "r.csv"
        report.write_csv(str(out), r)

        header = out.read_bytes().decode("utf-8-sig").splitlines()[0]
        assert header.endswith("excluded_by")
        assert header.startswith("root,path,type,status,codes,detail,action")


class TestJSON:
    """Documento unico, UTF-8 senza BOM, chiavi ordinate (§4.3)."""

    def test_no_bom_lf_only_and_readable_accents(self, tmp_path: Path) -> None:
        """I non-ASCII non vengono escapati: i nomi accentati devono restare
        leggibili nel file."""
        r = _report()
        r.rows = [_row(path="Città e Provincia.xlsx", codes=["CHR-001"])]
        out = tmp_path / "r.json"
        report.write_json(str(out), r)

        raw = out.read_bytes()
        assert not raw.startswith(report.UTF8_BOM)
        assert b"\r\n" not in raw
        assert "Città e Provincia.xlsx".encode() in raw

    def test_codes_is_an_array(self, tmp_path: Path) -> None:
        """codes e' un array, non una stringa: questo e' il formato per le
        macchine."""
        r = _report()
        r.rows = [_row(codes=["POS-001", "RSV-002"])]
        out = tmp_path / "r.json"
        report.write_json(str(out), r)

        doc = json.loads(out.read_bytes())
        assert doc["entries"][0]["codes"] == ["POS-001", "RSV-002"]

    def test_action_fields_absent_under_scan(self, tmp_path: Path) -> None:
        """I quattro campi azione sono assenti, non nulli, sotto scan: la loro
        assenza e' come un consumatore distingue le due forme."""
        r = _report()
        r.rows = [_row()]
        out = tmp_path / "r.json"
        report.write_json(str(out), r)

        entry = json.loads(out.read_bytes())["entries"][0]
        for field in ("action", "new_path", "outcome", "outcome_detail"):
            assert field not in entry

    def test_entries_always_present_even_if_empty(self, tmp_path: Path) -> None:
        """``entries`` e' sempre un array; header e summary sono emessi comunque."""
        out = tmp_path / "r.json"
        report.write_json(str(out), _report())

        doc = json.loads(out.read_bytes())
        assert doc["entries"] == []
        assert doc["summary"]["examined"] == 0
        assert doc["unicode_version"] == rules.UNICODE_VERSION

    def test_options_echo_patterns_verbatim(self, tmp_path: Path) -> None:
        """I pattern sono riportati come dati da riga di comando, ciascuno nel
        proprio array: un glob e una regex che si somigliano non significano
        la stessa cosa."""
        r = _report(options=report.Options(exclude=["*.tmp"], exclude_regex=[r"\.(bak|old)$"]))
        out = tmp_path / "r.json"
        report.write_json(str(out), r)

        opts = json.loads(out.read_bytes())["options"]
        assert opts["exclude"] == ["*.tmp"]
        assert opts["exclude_regex"] == [r"\.(bak|old)$"]


def test_manifest_is_jsonl(tmp_path: Path) -> None:
    """Il manifest resta JSONL, non un documento unico: e' uno stream (§1)."""
    entries = [
        walker.Entry(root="r", rel_path="a.txt", kind=rules.Kind.FILE, size=1, mtime="T"),
        walker.Entry(root="r", rel_path="b.txt", kind=rules.Kind.FILE, size=2, mtime="T"),
    ]
    out = tmp_path / "m.jsonl"
    report.write_manifest(str(out), entries)

    lines = out.read_bytes().decode("utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["path"] == "a.txt"


def test_console_says_so_when_there_is_nothing(tmp_path: Path) -> None:
    """Il silenzio e' indistinguibile da un crash: quando non c'e' nulla da
    riportare va detto esplicitamente (§4.1)."""
    buf = io.StringIO()
    report.write_console(buf, _report(), report.ConsoleOptions(width=120))

    assert "Nessuna violazione rilevata." in buf.getvalue()


def test_console_truncates_only_truncable_columns() -> None:
    """Su terminale stretto si elidono path e detail; root, status e codes mai
    (§4.1)."""
    r = _report()
    r.rows = [
        _row(
            path="Verbali/" + "x" * 200 + ".pdf",
            codes=["POS-008"],
            detail="una descrizione molto lunga " * 5,
        )
    ]
    buf = io.StringIO()
    report.write_console(buf, r, report.ConsoleOptions(width=80))

    body = buf.getvalue()
    assert "…" in body
    # Il codice resta leggibile per intero: e' il campo su cui si fa il triage.
    assert "POS-008" in body
    for line in body.splitlines():
        assert len(line) <= 80


def test_report_sorting_follows_root_order() -> None:
    """Le root escono nell'ordine di riga di comando, e dentro ciascuna in byte
    order del path (§5)."""
    r = _report(roots=["20 Tecnico", "10 Amministrazione"])
    r.rows = [
        _row(root="10 Amministrazione", path="b.pdf"),
        _row(root="20 Tecnico", path="z.pdf"),
        _row(root="10 Amministrazione", path="a.pdf"),
        _row(root="20 Tecnico", path="a.pdf"),
    ]
    r.sort()

    assert [(x.root, x.path) for x in r.rows] == [
        ("20 Tecnico", "a.pdf"),
        ("20 Tecnico", "z.pdf"),
        ("10 Amministrazione", "a.pdf"),
        ("10 Amministrazione", "b.pdf"),
    ]
