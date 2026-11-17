"""Backend di rinomina sul filesystem.

Il protocollo ``Renamer`` isola il trasporto: oggi esiste il solo backend
filesystem, ma un backend WebDAV MOVE contro il server NextCloud puo' essere
aggiunto senza toccare walker, rules o planner (Development guidelines §8.5).

Il rename diretto sul filesystem del server scavalca il database NextCloud e i
client vedono delete + create: e' accettabile per alberi non ancora condivisi,
non per alberi con share, versioni o commenti da preservare.
"""

import os
from pathlib import Path
from typing import Protocol

from .. import rules
from ..walker import long_path
from .temp import temp_name


class Renamer(Protocol):
    """Esegue una rinomina all'interno di una directory."""

    def rename(self, dir_abs: str, old_name: str, new_name: str) -> None:
        """Rinomina ``old_name`` in ``new_name`` dentro ``dir_abs``.

        Entrambi i nomi sono componenti singoli, non path.
        """
        ...

    def list(self, dir_abs: str) -> list[str]:
        """Restituisce i nomi presenti nella directory, letti in quel momento.

        Il chiamante lo usa per la verifica per ri-lettura (§9.3) e per il
        controllo di collisione contro il listing vivo (§8.2).
        """
        ...


class FSRenamer:
    """Backend filesystem."""

    def list(self, dir_abs: str) -> list[str]:
        """Legge il contenuto della directory dal filesystem."""
        return os.listdir(long_path(dir_abs))

    def rename(self, dir_abs: str, old_name: str, new_name: str) -> None:
        """Esegue la rinomina, gestendo il caso case-only con il doppio
        passaggio obbligatorio (§8.1).

        Non usa mai una replace nuda: su un filesystem case-insensitive
        rinominare "A.txt" in "b.txt" quando "B.txt" esiste sovrascriverebbe
        silenziosamente. La verifica di disponibilita' spetta al chiamante, che
        la esegue contro il listing vivo immediatamente prima (§8.2).
        """
        # Una rinomina che cambia solo il case e' rifiutata, ignorata o accettata
        # a seconda del filesystem e della versione di OS: non ci si puo' mai
        # contare. Il doppio passaggio la rende affidabile ovunque.
        if _is_case_only_change(old_name, new_name):
            self._rename_via_temp(dir_abs, old_name, new_name)
            return

        os.rename(
            long_path(os.path.join(dir_abs, old_name)),
            long_path(os.path.join(dir_abs, new_name)),
        )

    def _rename_via_temp(self, dir_abs: str, old_name: str, new_name: str) -> None:
        """Esegue la rinomina in due passi attraverso un nome temporaneo
        deterministico (§8.1).

            Bilancio.xlsx -> Bilancio.xlsx.safepath-<hash> -> bilancio.xlsx

        Il temporaneo sta nella stessa directory (evita EXDEV), ha un prefisso
        riconoscibile perche' una passata di recupero possa completare o
        annullare un'operazione interrotta, ed e' derivato da un hash del nome di
        destinazione cosi' che un'esecuzione andata in crash sia riprendibile.
        """
        tmp = temp_name(new_name)
        tmp_path = os.path.join(dir_abs, tmp)

        # Il temporaneo non deve gia' esistere: un residuo di un'esecuzione
        # precedente va riconosciuto, non sovrascritto.
        if Path(long_path(tmp_path)).exists():
            raise OSError(f"il nome temporaneo {tmp!r} esiste gia': recupero necessario")

        try:
            os.rename(long_path(os.path.join(dir_abs, old_name)), long_path(tmp_path))
        except OSError as exc:
            raise OSError(f"primo passo della rinomina case-only: {exc}") from exc

        try:
            os.rename(long_path(tmp_path), long_path(os.path.join(dir_abs, new_name)))
        except OSError as exc:
            # Il ripristino riporta il nome originale, cosi' che un fallimento
            # non lasci l'albero con un temporaneo al posto del file.
            try:
                os.rename(long_path(tmp_path), long_path(os.path.join(dir_abs, old_name)))
            except OSError as restore_exc:
                raise OSError(
                    f"secondo passo fallito ({exc}) e ripristino fallito "
                    f"({restore_exc}): il file resta come {tmp!r}"
                ) from exc
            raise OSError(f"secondo passo della rinomina case-only: {exc}") from exc


def _is_case_only_change(old_name: str, new_name: str) -> bool:
    """Riporta se i due nomi differiscono solo per il case, cioe' se hanno la
    stessa chiave di collisione ma non gli stessi byte."""
    return old_name != new_name and rules.collision_key(old_name) == rules.collision_key(new_name)
