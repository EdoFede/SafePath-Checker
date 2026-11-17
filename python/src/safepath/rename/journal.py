"""Journal delle rinomine eseguite."""

import json
from datetime import UTC, datetime
from types import TracebackType
from typing import BinaryIO


class Journal:
    """Registra ogni rinomina riuscita, in append, subito dopo l'operazione.

    E' un ausilio al recupero e una traccia di audit, non un input
    dell'esecuzione successiva: ``auto-rename`` ri-deriva sempre tutto dal
    filesystem (§9.4). Va archiviato insieme al report, perche' insieme
    documentano cio' che l'esecuzione intendeva fare e cio' che ha fatto davvero.
    """

    def __init__(self, path: str) -> None:
        # Modalita' binaria: il fine riga e' esplicito e non va lasciato alla
        # piattaforma (§5).
        self._f: BinaryIO = open(path, "ab")  # noqa: SIM115

    def record(self, dir_abs: str, old_name: str, new_name: str) -> None:
        """Annota una rinomina riuscita e forza la scrittura su disco.

        Un journal non sincronizzato non sopravvive al crash da cui deve
        proteggere.
        """
        line = json.dumps(
            {
                "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "dir": dir_abs,
                "old_name": old_name,
                "new_name": new_name,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._f.write(line.encode("utf-8") + b"\n")
        self._f.flush()

    def close(self) -> None:
        """Chiude il journal."""
        if not self._f.closed:
            self._f.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
