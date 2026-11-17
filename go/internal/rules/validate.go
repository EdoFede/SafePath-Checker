package rules

import (
	"sort"
	"strings"
	"unicode/utf8"
)

// Kind distingue file e directory, che hanno limiti di lunghezza diversi.
type Kind int

const (
	KindFile Kind = iota
	KindDir
)

// String restituisce il valore usato nella colonna type del report (§3.1).
func (k Kind) String() string {
	if k == KindDir {
		return "dir"
	}
	return "file"
}

// Target descrive l'entry da validare. RelPath e' il path relativo alla scan
// root con separatori "/", nella forma trovata su disco (non normalizzato):
// la normalizzazione e' cio' che CHR-002 deve poter rilevare.
type Target struct {
	RelPath   string // path relativo alla scan root, separatori "/"
	Kind      Kind
	ValidUTF8 bool // false per i nomi non decodificabili di Linux (§7.1)
}

// ValidateComponent verifica un singolo componente (nome di file o directory)
// contro charset, regole posizionali, nomi riservati e limiti di lunghezza che
// dipendono dal solo componente.
//
// I limiti che dipendono dal path intero (LEN-001, LEN-002, LEN-006) e
// l'unicita' (UNQ-001) non sono verificabili qui: vedi ValidatePath e
// CheckCollisions.
//
// I codici restituiti sono ordinati e deduplicati (§5).
func ValidateComponent(name string, kind Kind) []string {
	var codes codeSet

	if name == "" {
		return []string{CodePTH001}
	}

	codes.addAll(checkCharset(name))
	codes.addAll(checkPositional(name))
	codes.addAll(checkReserved(name))
	codes.addAll(checkComponentLength(name, kind))

	return codes.sorted()
}

// checkCharset verifica il set di caratteri e la forma NFC (§2, §5).
func checkCharset(name string) []string {
	var out []string

	if hasForbiddenChar(name) {
		out = append(out, CodeCHR001)
	}

	if !IsNFC(name) {
		out = append(out, CodeCHR002)
	}
	return out
}

// hasForbiddenChar riporta se name contiene un carattere fuori Profilo B.
//
// §2.3 vieta i marchi combinanti "standalone", non ogni marchio: in una
// sequenza NFD come "a"+U+0300 il marchio segue una base valida, e la sequenza
// e' gia' segnalata da CHR-002. Segnalare anche CHR-001 renderebbe
// irraggiungibile il vettore normativo di §8 per "Città" scritta in NFD.
func hasForbiddenChar(name string) bool {
	prevIsBase := false
	for _, r := range name {
		switch {
		case IsCombiningMark(r):
			if !prevIsBase {
				return true // marchio senza base: standalone
			}
			// La base resta valida: piu' marchi possono seguirla.
		case !IsAllowed(r):
			return true
		default:
			prevIsBase = IsAlnum(r)
		}
	}
	return false
}

// checkPositional verifica le otto regole posizionali di §3.
func checkPositional(name string) []string {
	var out []string

	// L'ordine dei controlli non influenza l'output: i codici sono ordinati
	// alla fine da codeSet.
	if strings.HasPrefix(name, "._") {
		out = append(out, CodePOS004)
	}
	if strings.HasPrefix(name, ".") {
		out = append(out, CodePOS001)
	}
	if strings.HasSuffix(name, ".") || strings.HasSuffix(name, ",") {
		out = append(out, CodePOS002)
	}
	// Lo spazio va cercato anche in coda al basename, non solo al componente:
	// "Riepilogo trimestrale .md" e' POS-003 nei vettori di §8, e la tabella di
	// rewrite §9 lo corregge in "Riepilogo trimestrale.md". Windows trimma lo
	// spazio prima dell'estensione esattamente come quello finale.
	base, _ := SplitExtension(name)
	if strings.HasPrefix(name, " ") || strings.HasSuffix(name, " ") ||
		strings.HasSuffix(base, " ") {
		out = append(out, CodePOS003)
	}
	if strings.HasPrefix(name, "-") {
		out = append(out, CodePOS005)
	}
	if strings.HasPrefix(name, "~") {
		out = append(out, CodePOS006)
	}
	if strings.Contains(name, "  ") {
		out = append(out, CodePOS007)
	}
	if strings.Contains(name, "..") {
		out = append(out, CodePOS008)
	}
	return out
}

// checkReserved verifica device names, basename ed estensioni riservate (§4).
func checkReserved(name string) []string {
	var out []string

	if IsWindowsDevice(name) {
		out = append(out, CodeRSV001)
	}
	if IsReservedBasename(name) {
		out = append(out, CodeRSV002)
	}
	if _, ext := SplitExtension(name); ext != "" && IsReservedExtension(ext) {
		out = append(out, CodeRSV003)
	}
	return out
}

// checkComponentLength verifica i limiti in caratteri e in byte del singolo
// componente (LEN-003, LEN-004, LEN-005).
//
// Entrambi i conteggi sono fatti su NFD, che e' il caso peggiore: un accento
// precomposto diventa due code point e fino a tre byte in piu' (§1, §5).
func checkComponentLength(name string, kind Kind) []string {
	var out []string
	nfd := ToNFD(name)

	chars := utf8.RuneCountInString(nfd)
	if kind == KindDir {
		if chars > DirNameMaxChars {
			out = append(out, CodeLEN004)
		}
	} else if chars > FileNameMaxChars {
		out = append(out, CodeLEN003)
	}

	if len(nfd) > ComponentMaxBytes {
		out = append(out, CodeLEN005)
	}
	return out
}

// ValidatePath valida un'entry completa: ogni componente del path relativo piu'
// i limiti che dipendono dal path nel suo insieme (LEN-001, LEN-002, LEN-006).
//
// La scan root non e' validata come componente: solo il suo contenuto
// (Development guidelines §2.1). RelPath e' quindi gia' relativo alla root.
//
// Per un'entry con ValidUTF8 false restituisce CHR-001 senza ulteriore analisi,
// perche' i byte non sono interpretabili come nome (§7.1).
func ValidatePath(t Target) []string {
	if t.RelPath == "" {
		return []string{CodePTH001}
	}
	if !t.ValidUTF8 {
		return []string{CodeCHR001}
	}

	var codes codeSet

	// Le regole di §2-§4 si applicano a un componente per volta: un file non
	// eredita le violazioni del nome della directory che lo contiene, che ha
	// gia' la propria riga nel report. Ripeterle su ogni discendente
	// gonfierebbe i conteggi e renderebbe illeggibile un albero profondo.
	components := strings.Split(t.RelPath, "/")
	codes.addAll(ValidateComponent(components[len(components)-1], t.Kind))

	// I limiti che dipendono dal path nel suo insieme appartengono invece
	// all'entry: e' il suo path a essere troppo lungo o troppo profondo.
	codes.addAll(checkPathLength(t))
	codes.addAll(checkDepth(t))

	return codes.sorted()
}

// checkPathLength verifica LEN-001 (path relativo) e LEN-002 (porzione di
// directory), entrambi in caratteri sulla forma NFD.
func checkPathLength(t Target) []string {
	var out []string

	if utf8.RuneCountInString(ToNFD(t.RelPath)) > RelPathMaxChars {
		out = append(out, CodeLEN001)
	}

	// La porzione di directory e' il path senza il componente finale e senza
	// separatore in coda. Per un'entry nella root e' vuota.
	dir := ""
	if i := strings.LastIndex(t.RelPath, "/"); i >= 0 {
		dir = t.RelPath[:i]
	}
	if utf8.RuneCountInString(ToNFD(dir)) > DirPathMaxChars {
		out = append(out, CodeLEN002)
	}
	return out
}

// checkDepth verifica LEN-006. La profondita' e' il numero di livelli di
// directory sotto la scan root, contata dal path argument e non dalla root del
// filesystem (Development guidelines §2.1, §7.3).
func checkDepth(t Target) []string {
	depth := strings.Count(t.RelPath, "/")
	// Per una directory, il componente finale e' esso stesso un livello.
	if t.Kind == KindDir {
		depth++
	}
	if depth > MaxDepth {
		return []string{CodeLEN006}
	}
	return nil
}

// CheckCollisions individua le collisioni case-insensitive fra i nomi di una
// singola directory e restituisce l'insieme dei nomi coinvolti (§5, UNQ-001).
//
// names e' il listing di una sola directory: il confronto fra directory diverse
// non ha significato. La chiave e' casefold(NFC(name)) (§6.2).
func CheckCollisions(names []string) map[string]bool {
	byKey := make(map[string][]string, len(names))
	for _, n := range names {
		k := CollisionKey(n)
		byKey[k] = append(byKey[k], n)
	}

	colliding := make(map[string]bool)
	for _, group := range byKey {
		if len(group) > 1 {
			for _, n := range group {
				colliding[n] = true
			}
		}
	}
	return colliding
}

// codeSet accumula codici di violazione deduplicandoli, e li restituisce
// ordinati per identificatore come richiesto dal contratto di determinismo (§5).
type codeSet struct {
	seen map[string]bool
}

func (c *codeSet) add(code string) {
	if c.seen == nil {
		c.seen = make(map[string]bool)
	}
	c.seen[code] = true
}

func (c *codeSet) addAll(codes []string) {
	for _, code := range codes {
		c.add(code)
	}
}

// sorted restituisce i codici ordinati. Restituisce nil (non slice vuota) se
// non ci sono violazioni, cosi' che il chiamante possa testare == nil.
func (c *codeSet) sorted() []string {
	if len(c.seen) == 0 {
		return nil
	}
	out := make([]string, 0, len(c.seen))
	for code := range c.seen {
		out = append(out, code)
	}
	sort.Strings(out)
	return out
}
