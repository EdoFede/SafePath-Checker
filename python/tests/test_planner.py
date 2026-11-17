"""Test del planner: remediation, risoluzione delle collisioni, suffissi."""

from pathlib import Path

import pytest

from safepath import planner, rules
from safepath.planner.charmap import CHAR_MAP


def test_charmap_produces_valid_chars() -> None:
    """Ogni sostituzione deve essere composta solo da caratteri del Profilo B.

    E' il vincolo che rende sicuro estendere la mappa: una sostituzione fuori
    profilo produrrebbe un nome ancora non conforme (charmap.py, criteri).
    """
    for source, repl in CHAR_MAP.items():
        for ch in repl:
            assert rules.is_allowed(ch), f"{source!r} -> {repl!r}: {ch!r} fuori profilo"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Tabella di rewrite di File naming Tech-rules §9.
        ("Offerta n° 12/2024 – Rossi & C. S.p.A.pdf", "Offerta n 12-2024 Rossi e C. S.p.A.pdf"),
        ("Elenco soci S.p.A..pdf", "Elenco soci S.p.A.pdf"),
        ("Elenco soci S.p.A.", "Elenco soci S.p.A"),
        ("Backup 2024-01-15 12:30.tar.gz", "Backup 2024-01-15 12h30.tar.gz"),
        ("Documento (rev.3) [DEF]!.docx", "Documento (rev.3) DEF.docx"),
        ("Riepilogo trimestrale .md", "Riepilogo trimestrale.md"),
        ("Report  finale.md", "Report finale.md"),
        ("~$bilancio.xlsx", "bilancio.xlsx"),
        ("-verbale.pdf", "verbale.pdf"),
        # Solo il punto iniziale viene rimosso: l'underscore e' ammesso dal
        # Profilo B e non e' illegale in testa, quindi resta.
        ("._appunti.md", "_appunti.md"),
    ],
)
def test_remediate_rewrite_examples(name: str, expected: str) -> None:
    """Le trasformazioni di riferimento producono nomi conformi."""
    got, unmapped = planner.remediate(name, rules.Kind.FILE)
    assert not unmapped
    assert got == expected
    assert rules.validate_component(got, rules.Kind.FILE) == []


def test_rewrite_table_is_transcribed_from_the_document() -> None:
    """Le attese di questo modulo devono coincidere con la tabella §9 letta dal
    documento, non con il comportamento corrente del codice.

    Il test estrae la tabella da ``docs/File naming Tech-rules.md`` e la
    confronta con i valori scritti a mano sopra: e' la guardia contro l'errore
    di "verificare" la remediation contro attese dedotte dall'implementazione.
    """
    doc = (Path(__file__).resolve().parents[2] / "docs" / "File naming Tech-rules.md").read_text(
        encoding="utf-8"
    )

    section = doc.split("## 9. Rewrite examples", 1)[1]
    pairs: dict[str, str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 3 or cells[0].startswith(("Non-compliant", "---")):
            continue
        source, _, expected = (c.strip("`") for c in cells)
        # L'ultima riga della tabella descrive una collisione fra due nomi, che
        # non e' una trasformazione di un singolo componente.
        if "+" in source:
            continue
        pairs[source] = expected

    assert len(pairs) == 7, f"tabella §9 non riconosciuta: {pairs}"
    for source, expected in pairs.items():
        got, unmapped = planner.remediate(source, rules.Kind.FILE)
        assert not unmapped, f"{source!r}: caratteri non mappati {unmapped}"
        assert got == expected, f"{source!r}: atteso {expected!r}, ottenuto {got!r}"
        assert rules.validate_component(got, rules.Kind.FILE) == []


def test_remediate_reserved_device_name() -> None:
    """Un device name Windows viene reso non riservato con un prefisso (§9)."""
    got, _ = planner.remediate("CON.docx", rules.Kind.FILE)
    assert got == "Contratto CON.docx"
    assert rules.validate_component(got, rules.Kind.FILE) == []


def test_remediate_reserved_dir_uses_dir_prefix() -> None:
    """Per una directory il prefisso e' "Cartella", non "Documento"."""
    got, _ = planner.remediate("CON", rules.Kind.DIR)
    assert got == "Cartella CON"


def test_remediate_unmapped_char_is_not_guessed() -> None:
    """Un carattere fuori profilo senza sostituzione non viene indovinato.

    L'entry diventa manual e il carattere finisce nel riepilogo (§3.2).
    """
    got, unmapped = planner.remediate("file \uf022 test.pdf", rules.Kind.FILE)
    assert got == ""
    assert unmapped == ["\uf022"]


def test_plan_collision_first_keeps_name() -> None:
    """Nel gruppo in collisione il primo conserva il nome, gli altri si spostano.

    Con l'ordine fissato per byte order, la risoluzione e' deterministica (§8.3).
    """
    names = sorted(["Bilancio.xlsx", "bilancio.xlsx"], key=rules.to_nfc)
    kinds = dict.fromkeys(names, rules.Kind.FILE)

    ops = {op.name: op for op in planner.plan(names, kinds)}

    assert ops["Bilancio.xlsx"].action is planner.Action.NONE
    assert ops["bilancio.xlsx"].action is planner.Action.RENAME
    assert ops["bilancio.xlsx"].target == "bilancio_1.xlsx"


def test_plan_suffix_goes_before_extension() -> None:
    """Il suffisso di collisione precede l'estensione (§8.3)."""
    names = ["a.txt", "A.txt"]
    names.sort(key=rules.to_nfc)
    ops = {op.name: op for op in planner.plan(names, dict.fromkeys(names, rules.Kind.FILE))}

    renamed = [op for op in ops.values() if op.action is planner.Action.RENAME]
    assert len(renamed) == 1
    assert renamed[0].target.endswith(".txt")
    assert "_1" in renamed[0].target


def test_plan_respects_live_directory() -> None:
    """Un nome gia' occupato nella directory viva non viene scelto come target.

    Le entry escluse restano occupanti: escluso significa "non toccare", non
    "non esiste" (§2.3, §8.2).
    """
    occupied = rules.collision_key("Report finale.md")
    ops = planner.plan(
        ["Report  finale.md"],
        {"Report  finale.md": rules.Kind.FILE},
        exists=lambda key: key == occupied,
    )
    assert ops[0].action is planner.Action.RENAME
    assert ops[0].target == "Report finale_1.md"


def test_plan_compliant_name_is_untouched() -> None:
    """Un nome gia' conforme non produce alcuna operazione."""
    ops = planner.plan(["Verbale CDA.docx"], {"Verbale CDA.docx": rules.Kind.FILE})
    assert ops[0].action is planner.Action.NONE


def test_unmapped_report_orders_by_codepoint() -> None:
    """Il riepilogo e' ordinato per code point, non per frequenza (§5)."""
    r = planner.UnmappedReport()
    r.add(["\uf028", "\uf022", "\uf022"])

    assert r.chars() == [("\uf022", 2), ("\uf028", 1)]
    assert not r.empty()
