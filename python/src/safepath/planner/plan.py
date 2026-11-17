"""Calcolo dei nomi di destinazione a partire dalle violazioni.

Non accede al filesystem: le verifiche di disponibilita' di un nome sono
iniettate dal chiamante come ``Lookup`` (Development guidelines §1, §8.2).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .. import rules
from .remediate import remediate

#: Riporta se un nome e' gia' presente nella directory, con confronto
#: case-insensitive sulla chiave di collisione.
#:
#: Deve interrogare il listing vivo della directory, mai una copia in cache: e'
#: la mitigazione della finestra TOCTOU di §9.2, dove il file distrutto e' uno
#: che il tool non ha mai guardato.
Lookup = Callable[[str], bool]

#: Oltre questo numero di tentativi l'entry e' legittimamente manual: il limite
#: tiene il caso patologico fuori da un ciclo illimitato.
_MAX_SUFFIX = 999


class Action(Enum):
    """Decisione del planner per un'entry (§3.2)."""

    NONE = "none"  # entry gia' conforme
    RENAME = "rename"  # esiste un nome di destinazione conforme
    MANUAL = "manual"  # non correggibile automaticamente

    def __str__(self) -> str:
        return self.value


@dataclass
class Operation:
    """Esito della pianificazione per una singola entry."""

    name: str  # nome originale, come trovato su disco
    action: Action
    target: str = ""  # nome di destinazione; solo se action is RENAME
    reason: str = ""  # motivo in italiano, per outcome_detail quando MANUAL
    unmapped: list[str] = field(default_factory=list)


def plan(
    names: list[str],
    kinds: dict[str, rules.Kind],
    exists: Lookup | None = None,
) -> list[Operation]:
    """Calcola le operazioni per un intero listing di directory.

    ``names`` e' il listing gia' ordinato per byte order del nome NFC (§7.3,
    §8.3): l'ordine fissato e' cio' che rende deterministica l'assegnazione dei
    suffissi di collisione. ``kinds`` associa a ogni nome il suo tipo.

    ``exists`` interroga la directory viva e deve gia' tenere conto delle entry
    escluse, che restano occupanti anche se non vanno rinominate (§2.3).
    """
    ops: list[Operation] = []

    # taken accumula le chiavi di collisione gia' impegnate in questo giro: i
    # nomi originali non ancora rinominati piu' le destinazioni assegnate. Senza
    # questo, due nomi che convergono sullo stesso target si sovrascriverebbero.
    taken = {rules.collision_key(n) for n in names}

    # Le collisioni case-insensitive gia' presenti nel listing di partenza.
    #
    # Solo i membri successivi al primo devono spostarsi: con l'ordine fissato
    # per byte order, il primo conserva il proprio nome e gli altri prendono il
    # suffisso, che e' la risoluzione deterministica di §8.3.
    colliding = rules.check_collisions(names)
    first_of_group: set[str] = set()

    for name in names:
        must_move = False
        if name in colliding:
            key = rules.collision_key(name)
            must_move = key in first_of_group  # il primo del gruppo resta dov'e'
            first_of_group.add(key)

        op = _plan_one(name, kinds.get(name, rules.Kind.FILE), must_move, taken, exists)

        # La destinazione scelta impegna la sua chiave e libera quella del nome
        # originale, che dopo il rename non esistera' piu'.
        if op.action is Action.RENAME:
            taken.discard(rules.collision_key(name))
            taken.add(rules.collision_key(op.target))
        ops.append(op)

    return ops


def _plan_one(
    name: str,
    kind: rules.Kind,
    has_collision: bool,
    taken: set[str],
    exists: Lookup | None,
) -> Operation:
    """Calcola l'operazione per una singola entry."""
    codes = rules.validate_component(name, kind)
    if not codes and not has_collision:
        return Operation(name=name, action=Action.NONE)

    candidate, unmapped = remediate(name, kind)
    if unmapped:
        return Operation(
            name=name,
            action=Action.MANUAL,
            reason=(
                "caratteri fuori profilo senza sostituzione prevista: " + _format_chars(unmapped)
            ),
            unmapped=unmapped,
        )
    if not candidate:
        return Operation(
            name=name,
            action=Action.MANUAL,
            reason="la correzione non lascia alcun nome utilizzabile",
        )

    # Il candidato deve essere libero: sia rispetto al listing corrente, sia
    # rispetto alla directory viva, che puo' contenere entry escluse.
    #
    # Quando la violazione e' la collisione stessa, il nome non puo' valere come
    # esenzione per se stesso: deve spostarsi su un nome distinto, altrimenti
    # resterebbe indefinitamente in conflitto con l'omonimo.
    self_name = "" if has_collision else name
    target = _resolve_free(candidate, self_name, kind, taken, exists)
    if target is None:
        return Operation(
            name=name,
            action=Action.MANUAL,
            reason="nessun nome conforme disponibile: troppe collisioni o limite di lunghezza",
        )

    # Un target identico all'originale significa che le violazioni rilevate non
    # sono correggibili per costruzione (per esempio una collisione gia' risolta
    # altrove): niente da fare.
    if target == name:
        return Operation(name=name, action=Action.NONE)

    return Operation(name=name, action=Action.RENAME, target=target)


def _resolve_free(
    candidate: str,
    original: str,
    kind: rules.Kind,
    taken: set[str],
    exists: Lookup | None,
) -> str | None:
    """Cerca il primo nome disponibile a partire da ``candidate``, aggiungendo
    se necessario un suffisso numerico progressivo (§8.3).

    Il suffisso e' inserito prima dell'estensione ("Bilancio_1.xlsx", non
    "Bilancio.xlsx_1") e il risultato e' rivalidato: il suffisso puo' spingere il
    nome oltre il limite di lunghezza.

    Restituisce ``None`` se nessun nome conforme e' disponibile: in quel caso
    l'entry e' manual, mai troncata. Accorciare il nome di un documento e' una
    decisione che il tool non e' autorizzato a prendere (§8.3).
    """
    # Il nome originale non e' un ostacolo per se stesso: viene liberato dal
    # rename. Le altre chiavi impegnate sono invece vincolanti.
    self_key = rules.collision_key(original)

    def free(n: str) -> bool:
        k = rules.collision_key(n)
        if k != self_key and k in taken:
            return False
        if k != self_key and exists is not None and exists(k):
            return False
        return not rules.validate_component(n, kind)

    if free(candidate):
        return candidate

    base, ext = rules.split_extension(candidate)
    for i in range(1, _MAX_SUFFIX + 1):
        suffixed = f"{base}_{i}{ext}"
        if free(suffixed):
            return suffixed
    return None


def _format_chars(chars: list[str]) -> str:
    """Rende leggibile un elenco di caratteri nel messaggio di errore.

    Il code point compare accanto al glifo perche' molti sono invisibili o
    simili fra loro.
    """
    return ", ".join(f"'{ch}' (U+{ord(ch):04X})" for ch in chars)


class UnmappedReport:
    """Raccoglie i caratteri privi di sostituzione incontrati durante
    un'esecuzione, per il riepilogo finale (§4.1)."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def add(self, chars: list[str]) -> None:
        """Registra i caratteri non mappati di un'operazione."""
        for ch in chars:
            self._counts[ch] = self._counts.get(ch, 0) + 1

    def chars(self) -> list[tuple[str, int]]:
        """Restituisce i caratteri raccolti, ordinati per code point.

        L'ordinamento e' per code point e non per frequenza: il contratto di
        determinismo vieta di emettere l'iterazione di una mappa, e due
        esecuzioni con gli stessi conteggi devono produrre lo stesso ordine (§5).
        """
        return sorted(self._counts.items(), key=lambda kv: ord(kv[0]))

    def empty(self) -> bool:
        """Riporta se non e' stato raccolto alcun carattere non mappato."""
        return not self._counts
