package planner

import (
	"testing"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// TestRewriteExamples verifica le trasformazioni della tabella di rewrite di
// File naming Tech-rules §9, che e' normativa per la remediation.
func TestRewriteExamples(t *testing.T) {
	cases := []struct {
		in   string
		kind rules.Kind
		want string
		why  string
	}{
		{
			in:   "Offerta n° 12-2024 – Rossi & C. S.p.A.pdf",
			kind: rules.KindFile,
			want: "Offerta n 12-2024 - Rossi e C. S.p.A.pdf",
			why:  "§9: °, –, & sostituiti; / non compare, nel path sarebbe un separatore",
		},
		{
			in:   "Elenco soci S.p.A..pdf",
			kind: rules.KindFile,
			want: "Elenco soci S.p.A.pdf",
			why:  "§9: .. prima dell'estensione",
		},
		{
			in:   "Elenco soci S.p.A.",
			kind: rules.KindFile,
			want: "Elenco soci S.p.A",
			why:  "§9: punto finale",
		},
		{
			in:   "Backup 2024-01-15 12:30.tar.gz",
			kind: rules.KindFile,
			want: "Backup 2024-01-15 12h30.tar.gz",
			why:  "§9: i due punti diventano h",
		},
		{
			in:   "Documento (rev.3) [DEF]!.docx",
			kind: rules.KindFile,
			want: "Documento (rev.3) (DEF).docx",
			why:  "§9: parentesi quadre e punto esclamativo",
		},
		{
			in:   "Riepilogo trimestrale .md",
			kind: rules.KindFile,
			want: "Riepilogo trimestrale.md",
			why:  "§9: spazio prima dell'estensione",
		},
		{
			in:   "CON.docx",
			kind: rules.KindFile,
			want: "Documento CON.docx",
			why:  "§9: device name Windows, prefisso descrittivo",
		},
	}

	for _, c := range cases {
		t.Run(c.in, func(t *testing.T) {
			got, unmapped := Remediate(c.in, c.kind)
			if len(unmapped) > 0 {
				t.Fatalf("Remediate(%q): caratteri non mappati %v\n  %s", c.in, unmapped, c.why)
			}
			if got != c.want {
				t.Errorf("Remediate(%q) = %q, atteso %q\n  %s", c.in, got, c.want, c.why)
			}
			// Una remediation che produce un nome ancora non conforme e' un bug
			// del planner, non un esito accettabile (§9.3).
			if codes := rules.ValidateComponent(got, c.kind); len(codes) > 0 {
				t.Errorf("Remediate(%q) = %q, ancora non conforme: %v", c.in, got, codes)
			}
		})
	}
}

// TestRemediateIsIdempotent verifica che un nome gia' conforme non venga
// toccato: e' il presupposto dell'idempotenza di auto-rename (§9.4).
func TestRemediateIsIdempotent(t *testing.T) {
	compliant := []string{
		"Verbale CDA 2026-08-06.md",
		"Offerta Rossi e C. S.p.A.pdf",
		"Nota n.12 del 3.4.2026.docx",
		"RELAZIONE FINALE.PDF",
		"Documento CON allegati.pdf",
		"archivio.tar.gz",
		"Bilancio (bozza), rev 2.xlsx",
		"Città e Provincia.xlsx",
	}

	for _, name := range compliant {
		t.Run(name, func(t *testing.T) {
			got, unmapped := Remediate(name, rules.KindFile)
			if len(unmapped) > 0 {
				t.Fatalf("Remediate(%q): caratteri non mappati %v", name, unmapped)
			}
			if got != name {
				t.Errorf("Remediate(%q) = %q, un nome conforme non va modificato", name, got)
			}
		})
	}
}

// TestCharMapProducesValidChars verifica che ogni sostituzione della mappa sia
// composta solo da caratteri del Profilo B. Una sostituzione non conforme
// produrrebbe un rename verso un nome ancora illegale.
func TestCharMapProducesValidChars(t *testing.T) {
	for r, repl := range charMap {
		for _, rr := range repl {
			if !rules.IsAllowed(rr) || rules.IsCombiningMark(rr) {
				t.Errorf("charMap[%q] = %q contiene il carattere non ammesso %q", r, repl, rr)
			}
		}
	}
}

// TestUnmappedCharsAreReported verifica che un carattere fuori profilo assente
// dalla mappa non venga indovinato, ma segnalato per il riepilogo finale.
func TestUnmappedCharsAreReported(t *testing.T) {
	// Un ideogramma non e' nel Profilo B e non ha una traslitterazione sensata.
	got, unmapped := Remediate("Relazione 日本.pdf", rules.KindFile)

	if len(unmapped) == 0 {
		t.Fatalf("Remediate ha restituito %q senza segnalare caratteri non mappati", got)
	}
	if got != "" {
		t.Errorf("con caratteri non mappati il nome deve essere vuoto, non %q", got)
	}
	want := []rune{'日', '本'}
	if len(unmapped) != len(want) {
		t.Fatalf("caratteri non mappati = %q, attesi %q", unmapped, want)
	}
	for i, r := range want {
		if unmapped[i] != r {
			t.Errorf("carattere non mappato %d = %q, atteso %q", i, unmapped[i], r)
		}
	}
}
