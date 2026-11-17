package walker

import "testing"

func TestGlobMatching(t *testing.T) {
	cases := []struct {
		pattern string
		name    string
		relPath string
		want    bool
		why     string
	}{
		{"*.tmp", "bozza.tmp", "a/bozza.tmp", true, "il glob sul nome cattura il file ovunque"},
		{"Archivio/*.tmp", "bozza.tmp", "Archivio/bozza.tmp", true, "pattern con / confrontato col path relativo"},
		{"Archivio/*.tmp", "bozza.tmp", "Altro/bozza.tmp", false, "path relativo diverso"},
		{"bozza", "bozza finale.docx", "bozza finale.docx", false, "l'intera stringa deve corrispondere, non una sottostringa"},
		{"*bozza*", "bozza finale.docx", "bozza finale.docx", true, "con i wildcard corrisponde"},
		{"*.TMP", "bozza.tmp", "bozza.tmp", true, "il confronto e' case-insensitive (§2.3)"},
		{"node_modules", "node_modules", "a/node_modules", true, "nome esatto di directory"},
	}

	for _, c := range cases {
		t.Run(c.pattern+" vs "+c.relPath, func(t *testing.T) {
			m, err := NewMatcher([]string{c.pattern}, nil)
			if err != nil {
				t.Fatalf("compilazione di %q: %v", c.pattern, err)
			}
			if _, got := m.Match(c.name, c.relPath); got != c.want {
				t.Errorf("Match(%q, %q) con glob %q = %v, atteso %v\n  %s",
					c.name, c.relPath, c.pattern, got, c.want, c.why)
			}
		})
	}
}

func TestRegexMatching(t *testing.T) {
	cases := []struct {
		pattern string
		name    string
		want    bool
		why     string
	}{
		{`\.bak$`, "documento.bak", true, "non ancorata di default: e' una ricerca (§2.3)"},
		{`\.bak$`, "documento.bak.pdf", false, "l'ancoraggio finale e' rispettato"},
		{`^~\$`, "~$bilancio.xlsx", true, "ancoraggio esplicito"},
		{`\.(bak|old)$`, "vecchio.old", true, "alternanza"},
		{`BOZZA`, "bozza.docx", true, "case-insensitive per §2.3"},
	}

	for _, c := range cases {
		t.Run(c.pattern+" vs "+c.name, func(t *testing.T) {
			m, err := NewMatcher(nil, []string{c.pattern})
			if err != nil {
				t.Fatalf("compilazione di %q: %v", c.pattern, err)
			}
			if _, got := m.Match(c.name, c.name); got != c.want {
				t.Errorf("Match(%q) con regex %q = %v, atteso %v\n  %s",
					c.name, c.pattern, got, c.want, c.why)
			}
		})
	}
}

// TestRejectsNonRE2 verifica che backreference e lookaround siano rifiutati a
// tempo di parsing.
//
// Vanno rifiutati in entrambe le implementazioni: Python accetterebbe un
// pattern che Go non puo' compilare, e la garanzia di parita' varrebbe solo
// fino al primo utilizzo (§2.3).
func TestRejectsNonRE2(t *testing.T) {
	invalid := []string{
		`(?=lookahead)`,
		`(?!negative)`,
		`(?<=lookbehind)`,
		`(a)\1`,
	}

	for _, p := range invalid {
		t.Run(p, func(t *testing.T) {
			if _, err := NewMatcher(nil, []string{p}); err == nil {
				t.Errorf("la regex %q e' stata accettata: RE2 non la supporta", p)
			}
		})
	}
}

// TestFirstMatchWins verifica che excluded_by riporti il primo pattern
// corrispondente in ordine di riga di comando, con i glob prima delle regex
// (§3.4).
func TestFirstMatchWins(t *testing.T) {
	m, err := NewMatcher([]string{"*.bak", "vecchio.*"}, []string{`\.bak$`})
	if err != nil {
		t.Fatalf("compilazione: %v", err)
	}

	p, ok := m.Match("vecchio.bak", "vecchio.bak")
	if !ok {
		t.Fatal("nessuna corrispondenza, attesa la prima")
	}
	if p.Raw != "*.bak" {
		t.Errorf("excluded_by = %q, atteso il primo glob %q", p.Raw, "*.bak")
	}
}

// TestBookkeepingSkips verifica gli skip incondizionati di §7.3, che non sono
// esclusioni: non vengono mai riportati, nemmeno con --show-excluded.
func TestBookkeepingSkips(t *testing.T) {
	skipped := []string{
		".nextcloud", ".sync_abc.db", ".owncloudsync.log",
		".owncloudsync.log.1", ".~lock.file.docx#", "~$bilancio.xlsx",
		"documento.part", "documento.filepart",
		"files_versions", "files_trashbin",
		"Bilancio.xlsx.safepath-a1b2c3d4e5f6",
	}
	for _, n := range skipped {
		if !IsBookkeeping(n) {
			t.Errorf("IsBookkeeping(%q) = false, atteso true", n)
		}
	}

	kept := []string{
		"documento.pdf", "Bilancio.xlsx", ".DS_Store", "partenza.docx",
	}
	for _, n := range kept {
		if IsBookkeeping(n) {
			t.Errorf("IsBookkeeping(%q) = true, non e' un file di servizio", n)
		}
	}
}
