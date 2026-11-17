package walker

import (
	"fmt"
	"path"
	"regexp"
	"strings"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// PatternKind distingue l'opzione da cui proviene un pattern, per la colonna
// detail delle righe escluse (§3.4).
type PatternKind string

const (
	PatternGlob  PatternKind = "--exclude"
	PatternRegex PatternKind = "--exclude-regex"
)

// Pattern e' un singolo pattern di esclusione compilato.
type Pattern struct {
	Kind PatternKind
	Raw  string // testo verbatim da riga di comando, per excluded_by (§3.4)

	folded  string         // glob: pattern normalizzato e case-folded
	re      *regexp.Regexp // regex: compilata con flag case-insensitive
	relOnly bool           // il pattern contiene "/": si confronta solo col path relativo
}

// Matcher raccoglie i pattern di esclusione nell'ordine di riga di comando.
//
// I due insiemi non competono mai: un'entry e' esclusa se corrisponde a un
// qualsiasi pattern dell'uno o dell'altro. Le esclusioni sono solo additive e
// non esiste un'opzione di inclusione che le riammetta (§2.3).
type Matcher struct {
	patterns []Pattern
}

// NewMatcher compila i pattern nell'ordine in cui vanno valutati: prima i glob,
// poi le regex, ciascun gruppo nell'ordine di riga di comando.
//
// L'ordine conta solo per excluded_by, che riporta il primo pattern che ha
// corrisposto (§3.4); l'esito dell'esclusione e' indipendente dall'ordine.
func NewMatcher(globs, regexes []string) (*Matcher, error) {
	m := &Matcher{}

	for _, g := range globs {
		// Un glob malformato va rifiutato subito: path.Match riporta l'errore
		// solo quando incontra il pattern, non alla compilazione.
		if _, err := path.Match(g, "x"); err != nil {
			return nil, fmt.Errorf("glob non valido %q: %w", g, err)
		}
		m.patterns = append(m.patterns, Pattern{
			Kind:    PatternGlob,
			Raw:     g,
			folded:  rules.FoldPattern(g),
			relOnly: strings.Contains(g, "/"),
		})
	}

	for _, r := range regexes {
		// La normalizzazione NFC del pattern precede la compilazione: un
		// pattern digitato su macOS puo' arrivare in NFD e non
		// corrisponderebbe al proprio bersaglio (§2.3).
		normalized := rules.ToNFC(r)

		if err := rejectNonRE2(normalized); err != nil {
			return nil, fmt.Errorf("regex non valida %q: %w", r, err)
		}
		// (?i) rende il match case-insensitive senza pre-foldare il pattern,
		// come richiesto da §2.3.
		re, err := regexp.Compile("(?i)" + normalized)
		if err != nil {
			return nil, fmt.Errorf("regex non valida %q: %w", r, err)
		}
		m.patterns = append(m.patterns, Pattern{
			Kind:    PatternRegex,
			Raw:     r,
			re:      re,
			relOnly: strings.Contains(r, "/"),
		})
	}
	return m, nil
}

// backrefOrLookaround individua i costrutti che RE2 non supporta ma che un
// utente abituato a PCRE puo' scrivere senza pensarci.
//
// Vanno rifiutati esplicitamente in entrambe le implementazioni: Python li
// accetterebbe e la garanzia di parita' varrebbe solo fino al primo uso (§2.3).
var backrefOrLookaround = regexp.MustCompile(`\\[1-9]|\(\?[=!<]`)

// rejectNonRE2 rifiuta backreference e lookaround prima della compilazione.
func rejectNonRE2(pattern string) error {
	// Le occorrenze precedute da backslash sono letterali, non costrutti.
	stripped := strings.ReplaceAll(pattern, `\\`, "")
	if backrefOrLookaround.MatchString(stripped) {
		return fmt.Errorf("backreference e lookaround non sono supportati da RE2")
	}
	return nil
}

// Match riporta il primo pattern che corrisponde all'entry, e ok=false se
// nessuno corrisponde.
//
// Il confronto avviene sia sul nome del componente sia sul path relativo alla
// scan root; un pattern che contiene "/" e' confrontato solo con il path
// relativo (§2.3). Il matching e' case-insensitive su casefold(NFC(...)).
func (m *Matcher) Match(name, relPath string) (Pattern, bool) {
	if m == nil || len(m.patterns) == 0 {
		return Pattern{}, false
	}

	foldedName := rules.FoldPattern(name)
	foldedRel := rules.FoldPattern(relPath)

	for _, p := range m.patterns {
		if p.matches(foldedName, foldedRel, name, relPath) {
			return p, true
		}
	}
	return Pattern{}, false
}

// matches valuta un singolo pattern. Le regex ricevono le stringhe non foldate,
// perche' la case-insensitivita' e' gia' nel flag (?i).
func (p *Pattern) matches(foldedName, foldedRel, name, relPath string) bool {
	if p.Kind == PatternRegex {
		// Non ancorata di default: una ricerca, non un match completo (§2.3).
		if p.relOnly {
			return p.re.MatchString(rules.ToNFC(relPath))
		}
		return p.re.MatchString(rules.ToNFC(name)) || p.re.MatchString(rules.ToNFC(relPath))
	}

	// Glob: l'intera stringa deve corrispondere, non una sottostringa.
	if p.relOnly {
		return globMatch(p.folded, foldedRel)
	}
	return globMatch(p.folded, foldedName) || globMatch(p.folded, foldedRel)
}

// globMatch applica la sintassi glob con il supporto di "**", che path.Match
// non ha: "*" non attraversa "/", "**" si.
func globMatch(pattern, s string) bool {
	if !strings.Contains(pattern, "**") {
		ok, err := path.Match(pattern, s)
		return err == nil && ok
	}

	// "**" viene tradotto confrontando i segmenti letterali attorno a esso.
	// Il caso comune ("prefix/**/suffix") si risolve senza un motore completo.
	parts := strings.Split(pattern, "**")
	rest := s
	for i, part := range parts {
		if part == "" {
			continue
		}
		switch {
		case i == 0:
			if !strings.HasPrefix(rest, part) && !hasGlobPrefix(part, rest) {
				return false
			}
			rest = strings.TrimPrefix(rest, part)
		case i == len(parts)-1:
			return strings.HasSuffix(rest, part) || hasGlobSuffix(part, rest)
		default:
			idx := strings.Index(rest, part)
			if idx < 0 {
				return false
			}
			rest = rest[idx+len(part):]
		}
	}
	return true
}

// hasGlobPrefix verifica un prefisso che contiene metacaratteri glob,
// confrontandolo segmento per segmento.
func hasGlobPrefix(pattern, s string) bool {
	segs := strings.SplitN(s, "/", strings.Count(pattern, "/")+2)
	if len(segs) == 0 {
		return false
	}
	candidate := strings.Join(segs[:min(len(segs), strings.Count(pattern, "/")+1)], "/")
	ok, err := path.Match(pattern, candidate)
	return err == nil && ok
}

// hasGlobSuffix verifica un suffisso che contiene metacaratteri glob contro le
// code progressive di s.
func hasGlobSuffix(pattern, s string) bool {
	segs := strings.Split(s, "/")
	for i := range segs {
		candidate := strings.Join(segs[i:], "/")
		if ok, err := path.Match(pattern, candidate); err == nil && ok {
			return true
		}
	}
	return false
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
