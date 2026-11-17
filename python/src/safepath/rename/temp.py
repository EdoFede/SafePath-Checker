"""Nomi temporanei del doppio passaggio e recupero dei residui."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ..walker import TEMP_PREFIX, long_path


def temp_name(target_name: str) -> str:
    """Costruisce il nome temporaneo per una destinazione.

    E' deterministico, derivato da un hash del nome di destinazione: cosi'
    un'esecuzione andata in crash puo' essere ripresa e il residuo riconosciuto.
    """
    digest = hashlib.sha256(target_name.encode("utf-8", "surrogateescape")).hexdigest()
    return target_name + TEMP_PREFIX + digest[:12]


@dataclass(frozen=True)
class Orphan:
    """Temporaneo rimasto da un'esecuzione interrotta."""

    dir: str  # directory che lo contiene
    name: str  # nome del temporaneo
    target: str  # nome di destinazione, ricavato dal nome stesso


def find_orphans(root: str) -> list[Orphan]:
    """Cerca i temporanei rimasti sotto ``root``.

    ``auto-rename`` deve essere tollerante ai crash: all'avvio cerca i residui
    "*.safepath-*" e li completa o li annulla (§8.1, §9.4).
    """
    orphans: list[Orphan] = []

    # onerror ignorato: una directory illeggibile non deve interrompere il
    # recupero, gli altri residui vanno comunque trovati.
    for dirpath, dirnames, filenames in os.walk(long_path(root)):
        for name in list(dirnames) + list(filenames):
            i = name.find(TEMP_PREFIX)
            if i > 0:
                orphans.append(Orphan(dir=dirpath, name=name, target=name[:i]))

    # Ordine fissato: il recupero deve essere riproducibile quanto il walk.
    orphans.sort(key=lambda o: (o.dir, o.name))
    return orphans


def recover_orphan(o: Orphan) -> None:
    """Completa un'operazione interrotta portando il temporaneo al nome di
    destinazione, se quel nome e' libero.

    Se la destinazione e' occupata il temporaneo viene lasciato dov'e' e l'errore
    riportato: rimuoverlo o sovrascrivere la destinazione sono decisioni che il
    tool non prende da solo.
    """
    tmp_path = os.path.join(o.dir, o.name)
    target_path = os.path.join(o.dir, o.target)

    if Path(long_path(target_path)).exists():
        raise OSError(
            f"il temporaneo {o.name!r} non puo' essere completato: {o.target!r} esiste gia'"
        )

    try:
        os.rename(long_path(tmp_path), long_path(target_path))
    except OSError as exc:
        raise OSError(f"completamento del temporaneo {o.name!r}: {exc}") from exc
