"""Test del walker: traversal, ordinamento, skip di bookkeeping, esclusioni."""

from pathlib import Path

import pytest

from safepath import rules, walker


def _tree(root: Path) -> None:
    """Crea un albero minimo con nomi conformi e non."""
    (root / "10 Amministrazione").mkdir()
    (root / "10 Amministrazione" / "Verbale CDA.docx").write_text("x")
    (root / "10 Amministrazione" / "Report  finale.md").write_text("x")
    (root / "20 Tecnico").mkdir()
    (root / "20 Tecnico" / "bozza.bak").write_text("x")
    (root / ".DS_Store").write_text("x")


def test_walk_orders_by_byte_order(tmp_path: Path) -> None:
    """Le entry escono ordinate per byte order del path NFC, mai in ordine di
    scoperta (§5)."""
    _tree(tmp_path)
    entries = walker.walk("root", str(tmp_path))
    paths = [e.rel_path for e in entries]
    assert paths == sorted(paths)


def test_walk_skips_bookkeeping(tmp_path: Path) -> None:
    """I file di servizio non compaiono mai nel report, nemmeno come esclusi
    (§2.3, §7.3)."""
    _tree(tmp_path)
    (tmp_path / "~$bilancio.xlsx").write_text("x")
    (tmp_path / "documento.part").write_text("x")
    (tmp_path / ".sync_abc.db").write_text("x")

    names = {e.name for e in walker.walk("root", str(tmp_path))}
    assert "~$bilancio.xlsx" not in names
    assert "documento.part" not in names
    assert ".sync_abc.db" not in names
    # Un .DS_Store non e' bookkeeping: e' una violazione da riportare.
    assert ".DS_Store" in names


def test_walk_skips_temp_leftovers(tmp_path: Path) -> None:
    """I temporanei di una esecuzione interrotta non inquinano il report (§8.1)."""
    (tmp_path / f"Bilancio.xlsx{walker.TEMP_PREFIX}abc123").write_text("x")
    assert walker.walk("root", str(tmp_path)) == []


def test_walk_does_not_follow_symlinks(tmp_path: Path) -> None:
    """I symlink sono registrati e saltati, mai attraversati (§7.3)."""
    target = tmp_path / "reale"
    target.mkdir()
    (target / "dentro.txt").write_text("x")
    (tmp_path / "link").symlink_to(target)

    entries = {e.name: e for e in walker.walk("root", str(tmp_path))}
    assert entries["link"].status is walker.Status.SKIPPED
    assert "symlink" in entries["link"].skip_reason


def test_walk_single_file_argument(tmp_path: Path) -> None:
    """Un argomento che punta a un file lo valida da solo (§2.1)."""
    f = tmp_path / "Report  finale.md"
    f.write_text("x")

    entries = walker.walk("f", str(f))
    assert len(entries) == 1
    assert entries[0].kind is rules.Kind.FILE


def test_walk_records_nfc_state(tmp_path: Path) -> None:
    """Il walker registra se il nome era gia' NFC, senza convertirlo (§6.3)."""
    nfd_name = "Città.docx"  # "Città" in NFD
    try:
        (tmp_path / nfd_name).write_text("x")
    except OSError:
        pytest.skip("il filesystem non conserva la forma NFD")

    entries = walker.walk("root", str(tmp_path))
    assert len(entries) == 1
    entry = entries[0]

    # Il path riportato e' NFC (§5), ma il flag conserva la forma trovata su
    # disco: e' l'informazione che rende visibile CHR-002, e che si perderebbe
    # convertendo silenziosamente.
    assert rules.is_nfc(entry.rel_path)
    if entry.nfc_normalized:
        pytest.skip("il filesystem ha normalizzato il nome in NFC alla creazione")
    assert rules.validate_component(nfd_name, rules.Kind.FILE) == [rules.codes.CHR_002]


def test_unreadable_directory_is_skipped_not_fatal(tmp_path: Path) -> None:
    """Una directory illeggibile e' una riga skipped e il walk prosegue (§7.3)."""
    locked = tmp_path / "chiusa"
    locked.mkdir()
    (locked / "dentro.txt").write_text("x")
    (tmp_path / "Verbale CDA.docx").write_text("x")
    locked.chmod(0o000)

    try:
        entries = {e.name: e for e in walker.walk("root", str(tmp_path))}
        assert entries["chiusa"].status is walker.Status.SKIPPED
        assert "Verbale CDA.docx" in entries  # il walk non si e' fermato
    finally:
        locked.chmod(0o755)


class TestExclusions:
    """Semantica dei pattern di esclusione (§2.3)."""

    def test_glob_matches_whole_string(self) -> None:
        """L'intera stringa deve corrispondere, non una sottostringa."""
        m = walker.Matcher(["bozza"], [])
        assert m.match("bozza", "bozza") is not None
        assert m.match("bozza finale.docx", "bozza finale.docx") is None

    def test_glob_star_does_not_cross_separator(self) -> None:
        """ "*" non attraversa "/", "**" si."""
        assert not walker.glob_match("a/*.tmp", "a/b/c.tmp")
        assert walker.glob_match("a/**", "a/b/c.tmp")

    def test_glob_with_slash_matches_relative_path_only(self) -> None:
        """Un pattern che contiene "/" si confronta col solo path relativo."""
        m = walker.Matcher(["Archivio/*.tmp"], [])
        assert m.match("x.tmp", "Archivio/x.tmp") is not None
        assert m.match("x.tmp", "Altro/x.tmp") is None

    def test_matching_is_case_insensitive(self) -> None:
        """Il confronto e' su casefold(NFC(...)), coerente con i client
        case-insensitive che il tool esiste per proteggere."""
        m = walker.Matcher(["*.TMP"], [])
        assert m.match("file.tmp", "file.tmp") is not None

    def test_regex_is_unanchored(self) -> None:
        """La regex e' una ricerca, non un match completo: e' il punto in cui
        diverge deliberatamente dal glob."""
        m = walker.Matcher([], [r"\.bak$"])
        assert m.match("bozza.bak", "bozza.bak") is not None
        assert m.match("bozza.txt", "bozza.txt") is None

    def test_first_matching_pattern_wins(self) -> None:
        """``excluded_by`` riporta il primo pattern corrispondente, con i glob
        prima delle regex (§3.4)."""
        m = walker.Matcher(["*.bak"], [r"\.bak$"])
        p = m.match("x.bak", "x.bak")
        assert p is not None
        assert p.kind == walker.GLOB

    @pytest.mark.parametrize("pattern", [r"(a)\1", "(?=foo)", "(?!foo)", "(?<=foo)"])
    def test_re2_incompatible_patterns_are_rejected(self, pattern: str) -> None:
        """Backreference e lookaround vanno rifiutati in entrambe le
        implementazioni, o la parita' varrebbe solo fino al primo uso (§2.3)."""
        with pytest.raises(walker.PatternError):
            walker.Matcher([], [pattern])

    def test_invalid_regex_is_rejected(self) -> None:
        """Una regex non compilabile non e' mai trattata come stringa
        letterale."""
        with pytest.raises(walker.PatternError):
            walker.Matcher([], ["("])

    def test_excluded_directory_subtree_is_not_walked(self, tmp_path: Path) -> None:
        """Escludere una directory esclude l'intero sottoalbero, che non viene
        proprio percorso: e' cio' che rende l'esclusione economica (§2.3)."""
        _tree(tmp_path)
        m = walker.Matcher(["20 Tecnico"], [])
        entries = walker.walk("root", str(tmp_path), walker.Options(matcher=m))

        excluded = [e for e in entries if e.status is walker.Status.EXCLUDED]
        assert [e.name for e in excluded] == ["20 Tecnico"]
        # Il contenuto non compare: una sola riga spiega tutto cio' che manca.
        assert not any(e.rel_path.startswith("20 Tecnico/") for e in entries)
