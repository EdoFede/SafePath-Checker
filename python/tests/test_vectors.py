"""Suite di regressione sui vettori normativi condivisi.

``shared/testvectors.json`` e' la fonte unica, consumata da entrambe le test
suite: nessuna implementazione ne tiene una copia propria, e nessuna delle due
e' autoritativa sul comportamento (Development guidelines §10).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from safepath import rules

VECTORS_PATH = Path(__file__).resolve().parents[2] / "shared" / "testvectors.json"


def _load() -> dict[str, Any]:
    # Letto in binario e decodificato esplicitamente: il file e' marcato binario
    # in .gitattributes e va confrontato byte per byte (§10).
    data: dict[str, Any] = json.loads(VECTORS_PATH.read_bytes().decode("utf-8"))
    return data


VECTORS = _load()


def _kind(name: str) -> rules.Kind:
    return rules.Kind.DIR if name == "dir" else rules.Kind.FILE


def _ids(items: list[dict[str, Any]], key: str) -> list[str]:
    return [repr(i[key]) for i in items]


@pytest.mark.parametrize(
    "vector", VECTORS["path_vectors"], ids=_ids(VECTORS["path_vectors"], "path")
)
def test_path_vectors(vector: dict[str, Any]) -> None:
    """Ogni path dei vettori produce esattamente i codici attesi."""
    target = rules.Target(rel_path=vector["path"], kind=_kind(vector["kind"]))
    assert rules.validate_path(target) == vector["codes"], vector["source"]


@pytest.mark.parametrize(
    "vector", VECTORS["component_vectors"], ids=_ids(VECTORS["component_vectors"], "name")
)
def test_component_vectors(vector: dict[str, Any]) -> None:
    """Ogni componente dei vettori produce esattamente i codici attesi."""
    got = rules.validate_component(vector["name"], _kind(vector["kind"]))
    assert got == vector["codes"], vector["source"]


@pytest.mark.parametrize(
    "vector", VECTORS["collision_vectors"], ids=range(len(VECTORS["collision_vectors"]))
)
def test_collision_vectors(vector: dict[str, Any]) -> None:
    """Le collisioni case-insensitive coinvolgono esattamente i nomi attesi."""
    got = rules.check_collisions(vector["names"])
    assert got == set(vector["colliding"]), vector["source"]


@pytest.mark.parametrize(
    "vector", VECTORS["extension_vectors"], ids=_ids(VECTORS["extension_vectors"], "name")
)
def test_extension_vectors(vector: dict[str, Any]) -> None:
    """L'estensione e' individuata secondo la regola deterministica di §3.1."""
    base, ext = rules.split_extension(vector["name"])
    assert (base, ext) == (vector["base"], vector["ext"]), vector["source"]


def test_unicode_version_is_pinned() -> None:
    """Le tabelle Unicode devono essere quelle dichiarate nell'header del report.

    Due esecuzioni con tabelle diverse non sono confrontabili, e la parita' con
    il binario Go vale solo a parita' di tabelle (§6.1).
    """
    assert rules.UNICODE_VERSION == "15.0.0"
