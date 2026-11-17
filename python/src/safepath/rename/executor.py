"""Applicazione delle rinomine durante la discesa del walk (§9.1)."""

import contextlib
import os
from dataclasses import dataclass, field

from .. import planner, rules
from ..walker import Entry, Status
from .journal import Journal
from .renamer import Renamer

#: Valori della colonna action (§3.2). "failed" non e' una decisione del
#: planner ma un rifiuto del filesystem, quindi vive qui e non in
#: ``planner.Action``: il planner decide, l'executor constata.
ACTION_NONE = "none"
ACTION_RENAME = "rename"
ACTION_MANUAL = "manual"
ACTION_FAILED = "failed"


@dataclass
class Result:
    """Esito di una rinomina per una singola entry."""

    rel_path: str  # path relativo originale
    action: str  # uno degli ACTION_* sopra
    outcome: str
    detail: str = ""
    new_path: str = ""  # path relativo risultante, vuoto se non rinominata
    unmapped: list[str] = field(default_factory=list)


class Executor:
    """Applica le rinomine mentre il walk discende."""

    def __init__(self, renamer: Renamer, journal: Journal | None = None) -> None:
        self.renamer = renamer
        self.journal = journal

        #: Registra se e' stata rilevata una deriva in una qualsiasi directory:
        #: determina l'exit code finale.
        self.drift = False

        self.results: dict[str, Result] = {}
        self.unmapped = planner.UnmappedReport()

    def process_dir(self, dir_abs: str, entries: list[Entry]) -> list[Entry]:
        """Esegue i passi 3..6 del ciclo per-directory (§9.1).

        Restituisce le entry aggiornate con i nomi definitivi, cosi' che il walk
        discenda sotto quelli.
        """
        # Il listing vivo, riletto adesso: il controllo di collisione non deve
        # mai girare su una copia in cache, perche' il file che verrebbe
        # distrutto e' uno che il tool non ha mai guardato (§8.2, §9.2).
        try:
            live = self.renamer.list(dir_abs)
        except OSError:
            return entries  # directory illeggibile: il walker l'ha gia' segnata

        if self._has_drift(entries, live):
            return self._abort_dir(entries)

        candidates, kinds = _rename_candidates(entries)
        if not candidates:
            return entries

        live_keys = {rules.collision_key(n) for n in live}
        ops = planner.plan(candidates, kinds, lambda key: key in live_keys)

        by_name: dict[str, planner.Operation] = {}
        for op in ops:
            by_name[op.name] = op
            self.unmapped.add(op.unmapped)

        renamed = self._apply_renames(dir_abs, entries, by_name)

        # La verifica avviene su una sola ri-lettura della directory a fine
        # rinomine: e' accettabile e piu' economica di una ri-lettura per entry,
        # purche' le conclusioni per entry siano tratte da quel listing (§9.3).
        if renamed:
            self._verify(dir_abs, renamed)

        return self._update_entries(entries)

    def _has_drift(self, entries: list[Entry], live: list[str]) -> bool:
        """Confronta il listing su cui il walker ha deciso con quello vivo.

        Una divergenza significa che qualcuno ha modificato la directory fra la
        lettura e adesso: la finestra TOCTOU non e' chiudibile, va rilevata
        (§9.2).
        """
        seen = {rules.to_nfc(n) for n in live}
        return any(
            rules.to_nfc(e.name) not in seen for e in entries if e.status is not Status.SKIPPED
        )

    def _abort_dir(self, entries: list[Entry]) -> list[Entry]:
        """Abbandona la directory corrente segnando ogni entry come fallita.

        L'esecuzione prosegue con il resto dell'albero: una directory volatile
        non e' un motivo per abbandonare un'esecuzione su un albero grande, ma e'
        un motivo per lasciare quella directory in pace (§9.2).
        """
        self.drift = True
        for e in entries:
            self.results[e.rel_path] = Result(
                rel_path=e.rel_path,
                action=ACTION_FAILED,
                outcome="error",
                detail="directory modificata durante l'esecuzione: nessuna rinomina tentata",
            )
        return entries

    def _apply_renames(
        self, dir_abs: str, entries: list[Entry], by_name: dict[str, planner.Operation]
    ) -> dict[str, str]:
        """Esegue le rinomine decise e restituisce le coppie riuscite."""
        renamed: dict[str, str] = {}

        for e in entries:
            if e.status in (Status.EXCLUDED, Status.SKIPPED):
                self.results[e.rel_path] = Result(
                    rel_path=e.rel_path,
                    action=ACTION_NONE,
                    outcome="skipped",
                    detail="entry esclusa o saltata: non viene rinominata",
                )
                continue

            # Un nome non decodificabile non permette di costruire una
            # destinazione: e' manual, non un tentativo alla cieca (§7.1).
            if not e.valid_utf8:
                self.results[e.rel_path] = Result(
                    rel_path=e.rel_path,
                    action=ACTION_MANUAL,
                    outcome="skipped",
                    detail="nome non decodificabile come UTF-8: destinazione non costruibile",
                )
                continue

            op = by_name.get(e.name)
            if op is None or op.action is planner.Action.NONE:
                self.results[e.rel_path] = Result(
                    rel_path=e.rel_path,
                    action=ACTION_NONE,
                    outcome="unchanged",
                    detail="entry conforme: nessuna azione necessaria",
                )
                continue

            if op.action is planner.Action.MANUAL:
                self.results[e.rel_path] = Result(
                    rel_path=e.rel_path,
                    action=ACTION_MANUAL,
                    outcome="skipped",
                    detail=op.reason,
                    unmapped=op.unmapped,
                )
                continue

            try:
                self.renamer.rename(dir_abs, e.name, op.target)
            except OSError as exc:
                # Un file bloccato o un rifiuto del filesystem e' riportato e
                # l'esecuzione prosegue; non si ritenta in ciclo (§8.4).
                self.results[e.rel_path] = Result(
                    rel_path=e.rel_path,
                    action=ACTION_FAILED,
                    outcome="error",
                    detail=f"rinomina rifiutata dal filesystem: {exc}",
                )
                continue

            if self.journal is not None:
                # Il journal e' un ausilio, non un vincolo: il suo fallimento
                # non annulla una rinomina gia' avvenuta.
                with contextlib.suppress(OSError):
                    self.journal.record(dir_abs, e.name, op.target)

            renamed[e.name] = op.target
            self.results[e.rel_path] = Result(
                rel_path=e.rel_path,
                action=ACTION_RENAME,
                outcome="ok",
                detail="rinominata",
                new_path=_replace_last(e.rel_path, op.target),
            )
        return renamed

    def _verify(self, dir_abs: str, renamed: dict[str, str]) -> None:
        """Conferma le rinomine rileggendo la directory (§9.3).

        Il ritorno positivo di ``rename()`` non e' una prova: le rinomine
        case-only sono ignorate in silenzio da alcuni filesystem, una
        normalizzazione NFC puo' essere ri-decomposta da un client HFS+, e un
        filesystem di rete puo' confermare un'operazione che non ha eseguito.
        """
        try:
            after = self.renamer.list(dir_abs)
        except OSError as exc:
            for old in renamed:
                self._mark_verify_failure(old, f"ri-lettura della directory fallita: {exc}")
            return

        # Il confronto e' sulle forme NFC, byte per byte.
        present = {rules.to_nfc(n) for n in after}

        for old, target in renamed.items():
            if rules.to_nfc(target) not in present:
                self._mark_verify_failure(
                    old,
                    f"il nome di destinazione {target!r} non risulta presente dopo la rinomina",
                )
            elif rules.to_nfc(old) in present and rules.collision_key(old) != rules.collision_key(
                target
            ):
                self._mark_verify_failure(old, f"il nome originale {old!r} risulta ancora presente")
            else:
                # Una rinomina che ha prodotto un nome ancora non conforme e' un
                # bug del planner, e il report deve mostrarlo invece di
                # nasconderlo.
                codes = rules.validate_component(target, rules.Kind.FILE)
                if codes:
                    self._mark_verify_failure(
                        old, f"il nome risultante {target!r} non e' conforme: {codes}"
                    )

    def _mark_verify_failure(self, old_name: str, reason: str) -> None:
        """Declassa a errore l'esito di una rinomina non confermata.

        Non si ritenta mai automaticamente: se il filesystem non ha fatto cio'
        che ha dichiarato, una seconda chiamata identica non ha piu'
        probabilita' di riuscire, e il tool non sa piu' in che stato si trova
        (§9.3).
        """
        for res in self.results.values():
            if res.action == ACTION_RENAME and _last_component(res.rel_path) == old_name:
                res.outcome = "error"
                res.detail = reason
                return

    def _update_entries(self, entries: list[Entry]) -> list[Entry]:
        """Riscrive i path delle entry rinominate, cosi' che il walker discenda
        sotto i nomi definitivi (§9.1).

        Una directory che non e' stata rinominata resta con il nome vecchio e il
        suo sottoalbero viene comunque esaminato: un padre non riparabile non
        esenta i figli dall'essere controllati.
        """
        for e in entries:
            res = self.results.get(e.rel_path)
            if res is not None and res.action == ACTION_RENAME and res.outcome == "ok":
                # Anche il path assoluto va aggiornato: il walker scende su
                # quello, e il nome vecchio su disco non esiste piu'.
                e.abs_path = os.path.join(
                    os.path.dirname(e.abs_path), _last_component(res.new_path)
                )
                # L'esito va indicizzato anche sotto il path nuovo: il report
                # legge le entry come il walk le restituisce, cioe' con il nome
                # definitivo, e senza questa chiave la rinomina non comparirebbe.
                self.results[res.new_path] = res
                e.rel_path = res.new_path
        return entries


def _rename_candidates(entries: list[Entry]) -> tuple[list[str], dict[str, rules.Kind]]:
    """Seleziona le entry rinominabili: non escluse, non saltate, decodificabili.

    Un'entry esclusa non viene mai rinominata, nemmeno come effetto collaterale,
    ma resta occupante ai fini delle collisioni: esclusa significa "non toccare",
    non "non esiste" (§2.3).
    """
    names: list[str] = []
    kinds: dict[str, rules.Kind] = {}

    for e in entries:
        if e.status in (Status.EXCLUDED, Status.SKIPPED):
            continue
        # Un nome non decodificabile non permette di costruire una destinazione
        # (§7.1).
        if not e.valid_utf8:
            continue
        names.append(e.name)
        kinds[e.name] = e.kind

    names.sort(key=rules.to_nfc)
    return names, kinds


def _replace_last(rel_path: str, new_name: str) -> str:
    """Sostituisce il componente finale di un path relativo."""
    i = rel_path.rfind("/")
    return rel_path[: i + 1] + new_name if i >= 0 else new_name


def _last_component(rel_path: str) -> str:
    """Restituisce il componente finale di un path relativo."""
    i = rel_path.rfind("/")
    return rel_path[i + 1 :] if i >= 0 else rel_path
