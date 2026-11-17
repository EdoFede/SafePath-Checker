"""Pattern di esclusione: glob e regex, entrambi ripetibili e additivi (§2.3)."""

import re
from dataclasses import dataclass

from .. import rules


class PatternError(ValueError):
    """Pattern non compilabile.

    Un pattern non valido non viene mai trattato come stringa letterale: e'
    exit 2 con il messaggio del compilatore (§2.3).
    """


#: Opzione da cui proviene un pattern, per la colonna detail delle righe
#: escluse (§3.4).
GLOB = "--exclude"
REGEX = "--exclude-regex"


@dataclass
class Pattern:
    """Singolo pattern di esclusione compilato."""

    kind: str
    raw: str  # testo verbatim da riga di comando, per excluded_by (§3.4)

    folded: str = ""  # glob: pattern normalizzato e case-folded
    regex: re.Pattern[str] | None = None  # regex: compilata case-insensitive
    rel_only: bool = False  # il pattern contiene "/": solo contro il path relativo

    def matches(self, folded_name: str, folded_rel: str, name: str, rel_path: str) -> bool:
        """Valuta il pattern contro nome e path relativo.

        Le regex ricevono le stringhe non foldate, perche' la
        case-insensitivita' e' gia' nel flag della compilazione.
        """
        if self.kind == REGEX:
            assert self.regex is not None
            # Non ancorata di default: una ricerca, non un match completo (§2.3).
            if self.rel_only:
                return self.regex.search(rules.to_nfc(rel_path)) is not None
            return (
                self.regex.search(rules.to_nfc(name)) is not None
                or self.regex.search(rules.to_nfc(rel_path)) is not None
            )

        # Glob: l'intera stringa deve corrispondere, non una sottostringa.
        if self.rel_only:
            return glob_match(self.folded, folded_rel)
        return glob_match(self.folded, folded_name) or glob_match(self.folded, folded_rel)


class Matcher:
    """Raccoglie i pattern di esclusione nell'ordine di riga di comando.

    I due insiemi non competono mai: un'entry e' esclusa se corrisponde a un
    qualsiasi pattern dell'uno o dell'altro. Le esclusioni sono solo additive e
    non esiste un'opzione di inclusione che le riammetta (§2.3).
    """

    def __init__(self, globs: list[str], regexes: list[str]) -> None:
        """Compila i pattern nell'ordine in cui vanno valutati: prima i glob,
        poi le regex, ciascun gruppo nell'ordine di riga di comando.

        L'ordine conta solo per ``excluded_by``, che riporta il primo pattern che
        ha corrisposto (§3.4); l'esito dell'esclusione e' indipendente
        dall'ordine.
        """
        self.patterns: list[Pattern] = []

        for g in globs:
            _validate_glob(g)
            self.patterns.append(
                Pattern(
                    kind=GLOB,
                    raw=g,
                    folded=rules.fold_pattern(g),
                    rel_only="/" in g,
                )
            )

        for r in regexes:
            # La normalizzazione NFC del pattern precede la compilazione: un
            # pattern digitato su macOS puo' arrivare in NFD e non
            # corrisponderebbe al proprio bersaglio (§2.3).
            normalized = rules.to_nfc(r)
            _reject_non_re2(normalized, r)
            try:
                # IGNORECASE rende il match case-insensitive senza pre-foldare
                # il pattern, come richiesto da §2.3.
                compiled = re.compile(normalized, re.IGNORECASE)
            except re.error as exc:
                raise PatternError(f"regex non valida {r!r}: {exc}") from exc
            self.patterns.append(Pattern(kind=REGEX, raw=r, regex=compiled, rel_only="/" in r))

    def __bool__(self) -> bool:
        return bool(self.patterns)

    def match(self, name: str, rel_path: str) -> Pattern | None:
        """Riporta il primo pattern che corrisponde all'entry, o ``None``.

        Il confronto avviene sia sul nome del componente sia sul path relativo
        alla scan root; un pattern che contiene "/" e' confrontato solo con il
        path relativo (§2.3). Il matching e' case-insensitive su
        ``casefold(NFC(...))``.
        """
        if not self.patterns:
            return None

        folded_name = rules.fold_pattern(name)
        folded_rel = rules.fold_pattern(rel_path)

        for p in self.patterns:
            if p.matches(folded_name, folded_rel, name, rel_path):
                return p
        return None


#: Costrutti che RE2 non supporta ma che un utente abituato a PCRE puo' scrivere
#: senza pensarci. Vanno rifiutati esplicitamente in entrambe le implementazioni:
#: Python li accetterebbe e la garanzia di parita' varrebbe solo fino al primo
#: uso (§2.3).
_BACKREF_OR_LOOKAROUND = re.compile(r"\\[1-9]|\(\?[=!<]")


def _reject_non_re2(pattern: str, raw: str) -> None:
    """Rifiuta backreference e lookaround prima della compilazione."""
    # Le occorrenze precedute da backslash sono letterali, non costrutti.
    stripped = pattern.replace("\\\\", "")
    if _BACKREF_OR_LOOKAROUND.search(stripped):
        raise PatternError(
            f"regex non valida {raw!r}: backreference e lookaround non sono supportati da RE2"
        )


def _validate_glob(pattern: str) -> None:
    """Rifiuta un glob malformato, cioe' con una classe di caratteri non chiusa.

    Va rilevato alla compilazione e non al primo confronto: un pattern che il
    motore non sa interpretare e' un errore d'uso, exit 2 (§2.3).
    """
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            j = i + 1
            if j < len(pattern) and pattern[j] == "^":
                j += 1
            closed = False
            while j < len(pattern):
                if pattern[j] == "\\":
                    j += 2
                    continue
                if pattern[j] == "]" and j > i + 1:
                    closed = True
                    break
                j += 1
            if not closed:
                raise PatternError(f"glob non valido {pattern!r}: classe di caratteri non chiusa")
            i = j + 1
            continue
        i += 1


def glob_match(pattern: str, s: str) -> bool:
    """Applica la sintassi glob con il supporto di "**".

    "*" non attraversa "/", "**" si. L'intera stringa deve corrispondere.
    """
    if "**" not in pattern:
        return _match_segment(pattern, s)

    # "**" viene tradotto confrontando i segmenti letterali attorno a esso. Il
    # caso comune ("prefix/**/suffix") si risolve senza un motore completo.
    parts = pattern.split("**")
    rest = s
    for i, part in enumerate(parts):
        if not part:
            continue
        if i == 0:
            if not (rest.startswith(part) or _has_glob_prefix(part, rest)):
                return False
            rest = rest.removeprefix(part)
        elif i == len(parts) - 1:
            return rest.endswith(part) or _has_glob_suffix(part, rest)
        else:
            idx = rest.find(part)
            if idx < 0:
                return False
            rest = rest[idx + len(part) :]
    return True


def _has_glob_prefix(pattern: str, s: str) -> bool:
    """Verifica un prefisso che contiene metacaratteri glob, segmento per
    segmento."""
    limit = pattern.count("/") + 1
    segs = s.split("/")
    candidate = "/".join(segs[:limit])
    return _match_segment(pattern, candidate)


def _has_glob_suffix(pattern: str, s: str) -> bool:
    """Verifica un suffisso che contiene metacaratteri glob contro le code
    progressive di ``s``."""
    segs = s.split("/")
    return any(_match_segment(pattern, "/".join(segs[i:])) for i in range(len(segs)))


def _match_segment(pattern: str, s: str) -> bool:
    """Match glob completo, con "*" e "?" che non attraversano "/".

    Implementato esplicitamente e non con ``fnmatch``, la cui "*" attraversa i
    separatori: la semantica da rispettare e' quella di §2.3, identica a quella
    del motore usato dall'implementazione Go.
    """
    return _match_here(pattern, 0, s, 0)


def _match_here(pattern: str, pi: int, s: str, si: int) -> bool:
    """Confronto ricorsivo con backtracking sulle sole "*"."""
    while pi < len(pattern):
        ch = pattern[pi]

        if ch == "*":
            # "*" non attraversa "/": il backtracking si ferma al separatore.
            pi += 1
            for end in range(si, len(s) + 1):
                if _match_here(pattern, pi, s, end):
                    return True
                if end < len(s) and s[end] == "/":
                    break
            return False

        if si >= len(s):
            return False

        if ch == "?":
            if s[si] == "/":
                return False
            pi, si = pi + 1, si + 1
            continue

        if ch == "[":
            ok, pi = _match_class(pattern, pi, s[si])
            if not ok:
                return False
            si += 1
            continue

        if ch == "\\" and pi + 1 < len(pattern):
            pi += 1
            ch = pattern[pi]

        if s[si] != ch:
            return False
        pi, si = pi + 1, si + 1

    return si == len(s)


def _match_class(pattern: str, pi: int, ch: str) -> tuple[bool, int]:
    """Valuta una classe "[...]" e restituisce l'esito e la posizione dopo "]"."""
    pi += 1  # salta "["
    negated = pi < len(pattern) and pattern[pi] == "^"
    if negated:
        pi += 1

    matched = False
    first = True
    while pi < len(pattern) and (pattern[pi] != "]" or first):
        first = False
        if pattern[pi] == "\\" and pi + 1 < len(pattern):
            pi += 1
        low = pattern[pi]
        pi += 1

        # Intervallo "a-z": il "-" finale prima di "]" e' letterale.
        if pi + 1 < len(pattern) and pattern[pi] == "-" and pattern[pi + 1] != "]":
            pi += 1
            if pattern[pi] == "\\" and pi + 1 < len(pattern):
                pi += 1
            high = pattern[pi]
            pi += 1
            if low <= ch <= high:
                matched = True
            continue

        if ch == low:
            matched = True

    if pi < len(pattern) and pattern[pi] == "]":
        pi += 1
    return (matched != negated) and ch != "/", pi
