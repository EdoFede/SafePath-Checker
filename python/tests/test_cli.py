"""Test della riga di comando: parsing, exit code, integrazione end-to-end."""

import io
import json
from pathlib import Path

import pytest

from safepath import cli


def _run(args: list[str]) -> tuple[int, str, str]:
    """Esegue il comando catturando stdout e stderr separatamente."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(args, out, err)
    return code, out.getvalue(), err.getvalue()


class TestParsing:
    """Regole di §2.1 e §2.2."""

    def test_command_is_required(self) -> None:
        with pytest.raises(cli.UsageError):
            cli.parse([])

    def test_unknown_command_is_rejected(self) -> None:
        with pytest.raises(cli.UsageError, match="comando sconosciuto"):
            cli.parse(["frobnicate", "."])

    def test_at_least_one_path_is_required(self) -> None:
        with pytest.raises(cli.UsageError, match="nessun path"):
            cli.parse(["scan"])

    def test_repeated_output_option_is_rejected(self) -> None:
        """Un --output-csv ripetuto da script e' un bug del chiamante, non una
        preferenza (§2.2)."""
        with pytest.raises(cli.UsageError, match="piu' volte"):
            cli.parse(["scan", ".", "--output-csv", "a.csv", "--output-csv", "b.csv"])

    def test_exclusions_are_repeatable(self) -> None:
        """Le esclusioni sono ripetibili per progetto e solo additive (§2.3)."""
        o = cli.parse(["scan", ".", "--exclude", "*.tmp", "--exclude", "*.bak"])
        assert o.exclude == ["*.tmp", "*.bak"]

    def test_inline_and_separate_values_are_equivalent(self) -> None:
        assert cli.parse(["scan", ".", "--output-csv=a.csv"]).output_csv == "a.csv"
        assert cli.parse(["scan", ".", "--output-csv", "a.csv"]).output_csv == "a.csv"

    def test_double_dash_ends_options(self) -> None:
        """Dopo "--" cio' che segue e' un path anche se inizia con un trattino."""
        assert cli.parse(["scan", "--", "-strano"]).paths == ["-strano"]

    def test_journal_only_applies_to_auto_rename(self) -> None:
        """scan non scrive mai, quindi non ha un journal (§9.4)."""
        with pytest.raises(cli.UsageError, match="--journal"):
            cli.parse(["scan", ".", "--journal", "j.jsonl"])

    def test_nested_paths_are_rejected(self, tmp_path: Path) -> None:
        """Argomenti annidati descriverebbero due volte lo stesso sottoalbero,
        con root diverse e profondita' incoerenti (§2.1)."""
        (tmp_path / "a" / "b").mkdir(parents=True)
        with pytest.raises(cli.UsageError, match="non possono annidarsi"):
            cli.parse(["scan", str(tmp_path / "a"), str(tmp_path / "a" / "b")])

    def test_repeated_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(cli.UsageError, match="piu' volte"):
            cli.parse(["scan", str(tmp_path), str(tmp_path)])


class TestExitCodes:
    """Tabella di §12."""

    def test_clean_tree_exits_zero(self, tmp_path: Path) -> None:
        (tmp_path / "Verbale CDA.docx").write_text("x")
        code, _, _ = _run(["scan", str(tmp_path)])
        assert code == cli.EXIT_OK

    def test_violations_exit_one(self, tmp_path: Path) -> None:
        """Le violazioni sono dati, non errori: exit 1 resta distinguibile da un
        crash perche' il tool sia scriptabile."""
        (tmp_path / "Report  finale.md").write_text("x")
        code, _, _ = _run(["scan", str(tmp_path)])
        assert code == cli.EXIT_VIOLATION

    def test_bad_arguments_exit_two(self) -> None:
        code, _, err = _run(["scan"])
        assert code == cli.EXIT_USAGE
        assert "Uso:" in err  # l'usage va su stderr, non su stdout

    def test_unusable_root_exits_two(self) -> None:
        code, _, _ = _run(["scan", "/percorso/che/non/esiste"])
        assert code == cli.EXIT_USAGE

    def test_auto_rename_that_fixed_everything_exits_zero(self, tmp_path: Path) -> None:
        """auto-rename e' fatto per correggere: un'esecuzione che ha riparato
        tutto esce 0. La domanda utile e' "c'e' ancora qualcosa?" (§12)."""
        (tmp_path / "Report  finale.md").write_text("x")
        code, _, _ = _run(["auto-rename", str(tmp_path)])

        assert code == cli.EXIT_OK
        assert (tmp_path / "Report finale.md").exists()


class TestOutput:
    """Comportamento degli output e dei due flag di visualizzazione."""

    def test_console_is_always_produced(self, tmp_path: Path) -> None:
        """Nessun output su file sopprime la tabella (§4)."""
        (tmp_path / "Report  finale.md").write_text("x")
        csv_path = tmp_path / "r.csv"

        _, out, _ = _run(["scan", str(tmp_path), "--output-csv", str(csv_path)])
        assert "safepath" in out
        assert csv_path.exists()

    def test_show_ok_changes_only_which_rows_are_emitted(self, tmp_path: Path) -> None:
        """Il flag non cambia il set di colonne, l'ordinamento o l'exit code
        (§3.3)."""
        # Gli output vanno fuori dall'albero scansionato, o comparirebbero
        # essi stessi fra le entry della scansione successiva.
        tree = tmp_path / "tree"
        tree.mkdir()
        (tree / "Verbale CDA.docx").write_text("x")
        (tree / "Report  finale.md").write_text("x")

        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        code_a, _, _ = _run(["scan", str(tree), "--output-json", str(a)])
        code_b, _, _ = _run(["scan", str(tree), "--show-ok", "--output-json", str(b)])

        assert code_a == code_b
        doc_a = json.loads(a.read_bytes())
        doc_b = json.loads(b.read_bytes())
        assert len(doc_a["entries"]) == 1
        assert len(doc_b["entries"]) == 2
        assert doc_a["summary"] == doc_b["summary"]  # il riepilogo non cambia

    def test_excluded_rows_need_the_flag(self, tmp_path: Path) -> None:
        """Di default un'entry esclusa non produce alcuna riga (§3.4)."""
        (tmp_path / "bozza.bak").write_text("x")

        a, b = tmp_path / "a.json", tmp_path / "b.json"
        _run(["scan", str(tmp_path), "--exclude", "*.bak", "--output-json", str(a)])
        _run(
            [
                "scan",
                str(tmp_path),
                "--exclude",
                "*.bak",
                "--show-excluded",
                "--output-json",
                str(b),
            ]
        )

        assert json.loads(a.read_bytes())["entries"] == []
        entry = json.loads(b.read_bytes())["entries"][0]
        assert entry["status"] == "excluded"
        assert entry["excluded_by"] == "*.bak"
        assert entry["detail"] == "--exclude"

    def test_excluded_never_affects_exit_code(self, tmp_path: Path) -> None:
        """Le entry escluse non contano mai per l'exit code (§2.3)."""
        (tmp_path / "Report  finale.md").write_text("x")
        code, _, _ = _run(["scan", str(tmp_path), "--exclude", "*.md"])
        assert code == cli.EXIT_OK

    def test_two_runs_are_byte_identical(self, tmp_path: Path) -> None:
        """Due scan su un albero immutato producono CSV e JSON byte-identici;
        l'unica variabile e' il timestamp dell'header (§5)."""
        (tmp_path / "Report  finale.md").write_text("x")

        outs = []
        for i in range(2):
            csv_p = tmp_path / f"r{i}.csv"
            _run(["scan", str(tmp_path), "--output-csv", str(csv_p)])
            outs.append(csv_p.read_bytes())

        assert outs[0] == outs[1]


def test_manifest_records_original_state(tmp_path: Path) -> None:
    """Il manifest archivia lo stato a cui il report si riferisce (§1)."""
    (tmp_path / "Report  finale.md").write_text("x")
    manifest = tmp_path / "m.jsonl"

    _run(["scan", str(tmp_path), "--emit-manifest", str(manifest)])

    lines = manifest.read_bytes().decode("utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["path"] == "Report  finale.md"


def test_auto_rename_is_idempotent(tmp_path: Path) -> None:
    """Una seconda esecuzione su un albero gia' corretto non rinomina nulla.

    E' il test end-to-end piu' forte disponibile (§9.4).
    """
    (tmp_path / "Report  finale.md").write_text("x")
    (tmp_path / "Documento (rev.3) [DEF]!.docx").write_text("x")

    _run(["auto-rename", str(tmp_path)])
    after_first = sorted(p.name for p in tmp_path.iterdir())

    code, out, _ = _run(["auto-rename", str(tmp_path)])
    assert sorted(p.name for p in tmp_path.iterdir()) == after_first
    assert code == cli.EXIT_OK
    assert "Rinominate 0" in out


def test_codes_describe_the_original_state_after_rename(tmp_path: Path) -> None:
    """Anche a rinomina riuscita, ``codes`` continua a descrivere lo stato
    trovato: un report i cui findings si svuotassero come effetto della
    correzione sarebbe inutile come traccia di audit (§3.2)."""
    (tmp_path / "Report  finale.md").write_text("x")
    out_json = tmp_path / "r.json"

    _run(["auto-rename", str(tmp_path), "--output-json", str(out_json)])

    entry = json.loads(out_json.read_bytes())["entries"][0]
    assert entry["path"] == "Report  finale.md"
    assert entry["codes"] == ["POS-007"]
    assert entry["action"] == "rename"
    assert entry["new_path"] == "Report finale.md"
    assert entry["outcome"] == "ok"
