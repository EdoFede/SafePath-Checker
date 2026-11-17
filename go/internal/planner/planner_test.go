package planner

import (
	"testing"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// planFixture esegue Plan su un listing di soli file, senza entry preesistenti
// oltre a quelle del listing.
func planFixture(names []string) []Operation {
	kinds := make(map[string]rules.Kind, len(names))
	for _, n := range names {
		kinds[n] = rules.KindFile
	}
	return Plan(names, kinds, nil)
}

// findOp cerca l'operazione relativa a un nome.
func findOp(ops []Operation, name string) *Operation {
	for i := range ops {
		if ops[i].Name == name {
			return &ops[i]
		}
	}
	return nil
}

// TestCollisionGetsSuffix verifica che una collisione case-insensitive sia
// risolta con un suffisso numerico progressivo, inserito prima dell'estensione
// (§8.3).
func TestCollisionGetsSuffix(t *testing.T) {
	// L'ordine e' quello del byte order del nome NFC, che e' cio' che rende
	// deterministica la scelta di chi prende il suffisso (§8.3).
	ops := planFixture([]string{"Bilancio.xlsx", "bilancio.xlsx"})

	first := findOp(ops, "Bilancio.xlsx")
	second := findOp(ops, "bilancio.xlsx")
	if first == nil || second == nil {
		t.Fatalf("operazioni mancanti: %+v", ops)
	}

	// Uno dei due deve cambiare nome; entrambi non possono restare.
	if first.Action == ActionNone && second.Action == ActionNone {
		t.Fatal("nessuno dei due nomi in collisione e' stato modificato")
	}

	renamed := first
	if first.Action != ActionRename {
		renamed = second
	}
	if renamed.Action != ActionRename {
		t.Fatalf("nessuna rinomina pianificata: %+v", ops)
	}

	// Il suffisso va prima dell'estensione: "Bilancio_1.xlsx", non
	// "Bilancio.xlsx_1".
	_, ext := rules.SplitExtension(renamed.Target)
	if ext != ".xlsx" {
		t.Errorf("target %q: il suffisso deve precedere l'estensione", renamed.Target)
	}
	if len(rules.ValidateComponent(renamed.Target, rules.KindFile)) > 0 {
		t.Errorf("target %q non conforme", renamed.Target)
	}
}

// TestPlanIsDeterministic verifica che lo stesso listing produca sempre le
// stesse decisioni: senza, la scelta di chi prende il suffisso varierebbe per
// piattaforma (§8.3).
func TestPlanIsDeterministic(t *testing.T) {
	names := []string{"Bilancio.xlsx", "bilancio.xlsx", "BILANCIO.xlsx"}

	first := planFixture(names)
	for i := 0; i < 10; i++ {
		again := planFixture(names)
		for j := range first {
			if first[j].Name != again[j].Name || first[j].Target != again[j].Target {
				t.Fatalf("esecuzione %d divergente: %q->%q invece di %q->%q",
					i, again[j].Name, again[j].Target, first[j].Name, first[j].Target)
			}
		}
	}
}

// TestTargetsAreUnique verifica che due entry non convergano mai sullo stesso
// nome di destinazione: sarebbe una sovrascrittura silenziosa (§8.2).
func TestTargetsAreUnique(t *testing.T) {
	// Questi tre nomi si correggono tutti verso la stessa forma.
	ops := planFixture([]string{"Report  finale.md", "Report   finale.md", "Report finale.md"})

	seen := map[string]string{}
	for _, op := range ops {
		target := op.Name
		if op.Action == ActionRename {
			target = op.Target
		}
		key := rules.CollisionKey(target)
		if prev, dup := seen[key]; dup {
			t.Errorf("%q e %q convergono entrambi su %q", prev, op.Name, target)
		}
		seen[key] = op.Name
	}
}

// TestExistingNamesAreRespected verifica che il planner non proponga un nome
// gia' presente nella directory viva, incluse le entry escluse: escluso
// significa "non toccare", non "non esiste" (§2.3).
func TestExistingNamesAreRespected(t *testing.T) {
	occupied := rules.CollisionKey("Report finale.md")
	kinds := map[string]rules.Kind{"Report  finale.md": rules.KindFile}

	ops := Plan([]string{"Report  finale.md"}, kinds, func(key string) bool {
		return key == occupied
	})

	if len(ops) != 1 {
		t.Fatalf("attesa una operazione, ottenute %d", len(ops))
	}
	if ops[0].Action == ActionRename && rules.CollisionKey(ops[0].Target) == occupied {
		t.Errorf("il planner ha scelto %q, che e' gia' occupato", ops[0].Target)
	}
}

// TestCompliantNamesAreUntouched verifica che un'entry conforme non produca
// alcuna azione: e' il presupposto dell'idempotenza (§9.4).
func TestCompliantNamesAreUntouched(t *testing.T) {
	ops := planFixture([]string{"Verbale CDA 2026-08-06.md", "archivio.tar.gz"})

	for _, op := range ops {
		if op.Action != ActionNone {
			t.Errorf("%q e' conforme ma ha prodotto l'azione %q verso %q",
				op.Name, op.Action, op.Target)
		}
	}
}

// TestUnmappedCharsBecomeManual verifica che un nome con caratteri fuori
// profilo non mappati diventi manual invece di essere indovinato.
func TestUnmappedCharsBecomeManual(t *testing.T) {
	ops := planFixture([]string{"Relazione 日本.pdf"})

	if len(ops) != 1 {
		t.Fatalf("attesa una operazione, ottenute %d", len(ops))
	}
	if ops[0].Action != ActionManual {
		t.Errorf("azione = %q, atteso manual per i caratteri non mappati", ops[0].Action)
	}
	if len(ops[0].Unmappa) == 0 {
		t.Error("i caratteri non mappati non sono stati riportati per il riepilogo")
	}
}

// TestUnmappedReportIsSorted verifica che il riepilogo esca ordinato per code
// point e non per ordine di iterazione di una mappa (§5).
func TestUnmappedReportIsSorted(t *testing.T) {
	u := NewUnmappedReport()
	u.Add([]rune{'本', '日', '本'})

	chars := u.Chars()
	if len(chars) != 2 {
		t.Fatalf("attesi 2 caratteri distinti, ottenuti %d", len(chars))
	}
	if chars[0].Rune >= chars[1].Rune {
		t.Errorf("il riepilogo non e' ordinato per code point: %v", chars)
	}
	if chars[0].Rune == '日' && chars[0].Count != 1 {
		t.Errorf("conteggio di 日 = %d, atteso 1", chars[0].Count)
	}
}
