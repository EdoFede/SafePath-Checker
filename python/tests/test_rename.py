"""Test delle rinomine: case-only, verifica per ri-lettura, deriva, recupero."""

from pathlib import Path

import pytest

from safepath import planner, rename, rules, walker


def _case_sensitive(tmp_path: Path) -> bool:
    """Rileva se il filesystem distingue il case.

    I test che dipendono dalla case-sensitivity vanno scritti in modo da
    rilevarla e fare skip esplicito, non da assumerla: la stessa suite gira su
    APFS, NTFS ed ext4.
    """
    probe = tmp_path / "_probe_CASE"
    probe.write_text("x")
    result = not (tmp_path / "_probe_case").exists()
    probe.unlink()
    return result


def test_temp_name_is_deterministic() -> None:
    """Il temporaneo e' derivato da un hash del nome di destinazione, cosi' che
    un'esecuzione andata in crash sia riprendibile (§8.1)."""
    assert rename.temp_name("bilancio.xlsx") == rename.temp_name("bilancio.xlsx")
    assert rename.temp_name("a.txt") != rename.temp_name("b.txt")
    assert walker.TEMP_PREFIX in rename.temp_name("a.txt")


def test_temp_name_is_skipped_by_walk() -> None:
    """Il temporaneo deve essere invisibile al walk, o un'esecuzione interrotta
    inquinerebbe il report successivo con i propri detriti (§8.1)."""
    assert walker.is_bookkeeping(rename.temp_name("bilancio.xlsx"))


def test_case_only_rename_uses_two_steps(tmp_path: Path) -> None:
    """Una rinomina case-only passa dal temporaneo: il rename diretto e'
    rifiutato o ignorato a seconda del filesystem (§8.1)."""
    src = tmp_path / "Bilancio.xlsx"
    src.write_text("contenuto")

    rename.FSRenamer().rename(str(tmp_path), "Bilancio.xlsx", "bilancio.xlsx")

    names = list(tmp_path.iterdir())
    assert len(names) == 1
    assert names[0].name == "bilancio.xlsx"
    assert names[0].read_text() == "contenuto"
    # Nessun residuo del passaggio intermedio.
    assert not list(tmp_path.glob(f"*{walker.TEMP_PREFIX}*"))


def test_rename_reports_filesystem_refusal(tmp_path: Path) -> None:
    """Un rifiuto del filesystem e' riportato e l'esecuzione prosegue; non si
    ritenta in ciclo (§8.4)."""
    ex = rename.Executor(_FailingRenamer(["Report  finale.md"]))
    entries = [
        walker.Entry(
            root="r",
            rel_path="Report  finale.md",
            kind=rules.Kind.FILE,
            abs_path=str(tmp_path / "Report  finale.md"),
        )
    ]
    ex.process_dir(str(tmp_path), entries)

    res = ex.results["Report  finale.md"]
    assert res.action == rename.ACTION_FAILED
    assert res.outcome == "error"


def test_drift_aborts_only_the_current_directory(tmp_path: Path) -> None:
    """Su deriva la directory corrente e' abbandonata e ogni entry e' failed, ma
    il resto dell'albero prosegue (§9.2)."""
    ex = rename.Executor(_EmptyRenamer())
    entries = [walker.Entry(root="r", rel_path="sparito.txt", kind=rules.Kind.FILE, abs_path="x")]
    ex.process_dir(str(tmp_path), entries)

    assert ex.drift is True
    assert ex.results["sparito.txt"].action == rename.ACTION_FAILED
    assert ex.results["sparito.txt"].outcome == "error"


def test_excluded_entry_is_never_renamed(tmp_path: Path) -> None:
    """Un'entry esclusa non viene mai rinominata, nemmeno come effetto
    collaterale: esclusa significa "non toccare" (§2.3)."""
    (tmp_path / "Report  finale.md").write_text("x")

    ex = rename.Executor(rename.FSRenamer())
    entries = [
        walker.Entry(
            root="r",
            rel_path="Report  finale.md",
            kind=rules.Kind.FILE,
            status=walker.Status.EXCLUDED,
            excluded_by="*.md",
            abs_path=str(tmp_path / "Report  finale.md"),
        )
    ]
    ex.process_dir(str(tmp_path), entries)

    # Cio' che conta e' il file intatto: quando la directory non ha alcun
    # candidato rinominabile l'executor non produce nemmeno un esito, e la riga
    # riceve dal report le colonne none/unchanged.
    assert (tmp_path / "Report  finale.md").exists()
    res = ex.results.get("Report  finale.md")
    assert res is None or res.outcome == "skipped"


def test_verification_detects_unperformed_rename(tmp_path: Path) -> None:
    """Il ritorno positivo di rename() non e' una prova: se la ri-lettura non
    conferma, l'esito e' error (§9.3)."""
    ex = rename.Executor(_LyingRenamer())
    entries = [
        walker.Entry(
            root="r",
            rel_path="Report  finale.md",
            kind=rules.Kind.FILE,
            abs_path=str(tmp_path / "Report  finale.md"),
        )
    ]
    ex.process_dir(str(tmp_path), entries)

    res = ex.results["Report  finale.md"]
    assert res.outcome == "error"
    assert "non risulta presente" in res.detail


def test_find_and_recover_orphan(tmp_path: Path) -> None:
    """Un temporaneo rimasto viene individuato e portato a destinazione (§9.4)."""
    orphan_name = rename.temp_name("bilancio.xlsx")
    (tmp_path / orphan_name).write_text("dati")

    orphans = rename.find_orphans(str(tmp_path))
    assert len(orphans) == 1
    assert orphans[0].target == "bilancio.xlsx"

    rename.recover_orphan(orphans[0])
    assert (tmp_path / "bilancio.xlsx").read_text() == "dati"


def test_recover_orphan_refuses_to_overwrite(tmp_path: Path) -> None:
    """Se la destinazione e' occupata il temporaneo resta dov'e': sovrascrivere
    non e' una decisione che il tool prende da solo (§9.4)."""
    (tmp_path / "bilancio.xlsx").write_text("esistente")
    orphan_name = rename.temp_name("bilancio.xlsx")
    (tmp_path / orphan_name).write_text("dati")

    with pytest.raises(OSError, match="esiste gia'"):
        rename.recover_orphan(rename.find_orphans(str(tmp_path))[0])

    assert (tmp_path / "bilancio.xlsx").read_text() == "esistente"


def test_journal_records_renames(tmp_path: Path) -> None:
    """Il journal annota ogni rinomina riuscita, in append (§9.4)."""
    path = tmp_path / "journal.jsonl"
    with rename.Journal(str(path)) as j:
        j.record("/dir", "vecchio.txt", "nuovo.txt")
        j.record("/dir", "a.txt", "b.txt")

    lines = path.read_bytes().decode("utf-8").splitlines()
    assert len(lines) == 2
    assert '"old_name":"vecchio.txt"' in lines[0].replace(", ", ",").replace('": ', '":')


def test_collision_pair_is_resolved_deterministically(tmp_path: Path) -> None:
    """Su filesystem case-sensitive, la coppia in collisione viene risolta
    dando il suffisso al secondo in byte order (§8.3)."""
    if not _case_sensitive(tmp_path):
        pytest.skip("il filesystem non distingue il case: la fixture non e' creabile")

    (tmp_path / "Bilancio.xlsx").write_text("a")
    (tmp_path / "bilancio.xlsx").write_text("b")

    names = sorted(["Bilancio.xlsx", "bilancio.xlsx"], key=rules.to_nfc)
    ops = {op.name: op for op in planner.plan(names, dict.fromkeys(names, rules.Kind.FILE))}
    assert ops["Bilancio.xlsx"].action is planner.Action.NONE
    assert ops["bilancio.xlsx"].target == "bilancio_1.xlsx"


class _FailingRenamer:
    """Backend che rifiuta le rinomine dei nomi indicati, come un file bloccato."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    def list(self, dir_abs: str) -> list[str]:
        return list(self._names)

    def rename(self, dir_abs: str, old_name: str, new_name: str) -> None:
        raise OSError("file bloccato da un'altra applicazione")


class _EmptyRenamer:
    """Backend il cui listing non contiene le entry attese: simula la deriva."""

    def list(self, dir_abs: str) -> list[str]:
        return []

    def rename(self, dir_abs: str, old_name: str, new_name: str) -> None:
        raise AssertionError("nessuna rinomina deve essere tentata su deriva")


class _LyingRenamer:
    """Backend che dichiara il successo senza eseguire nulla, come un filesystem
    di rete che conferma un'operazione che non ha svolto."""

    def list(self, dir_abs: str) -> list[str]:
        return ["Report  finale.md"]

    def rename(self, dir_abs: str, old_name: str, new_name: str) -> None:
        return None
