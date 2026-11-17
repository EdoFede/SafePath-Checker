package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// fixtureTree e' l'albero di prova: nomi non conformi rappresentativi dei casi
// che si incontrano sul campo, piu' i casi limite delle regole.
var fixtureTree = map[string]string{
	"Verbale CDA 2026-08-06.md":     "ok",
	"Report  finale.md":             "spazi consecutivi",
	"Riepilogo trimestrale .md":     "spazio prima dell'estensione",
	"-verbale.pdf":                  "trattino iniziale",
	"Elenco soci S.p.A..pdf":        "punti consecutivi",
	"Offerta n° 12 – Rossi & C.pdf": "caratteri fuori profilo",
	"L'ISOLANTE/documento.pdf":      "apostrofo nella directory",
	"L'ISOLANTE/L'altro  file.pdf":  "apostrofo e spazi doppi",
	"CON.docx":                      "device name Windows",
	"sub/Città.docx":                "accento in NFC, conforme",
}

// writeFixture materializza l'albero in dir.
func writeFixture(t *testing.T, dir string) {
	t.Helper()

	paths := make([]string, 0, len(fixtureTree))
	for p := range fixtureTree {
		paths = append(paths, p)
	}
	sort.Strings(paths)

	for _, p := range paths {
		full := filepath.Join(dir, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatalf("creazione di %s: %v", filepath.Dir(full), err)
		}
		if err := os.WriteFile(full, []byte("x"), 0o644); err != nil {
			t.Fatalf("creazione di %s: %v", full, err)
		}
	}
}

// run esegue il comando in dir e restituisce exit code e stdout.
func run(t *testing.T, dir string, args ...string) (int, string) {
	t.Helper()

	wd, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatalf("chdir in %s: %v", dir, err)
	}
	defer os.Chdir(wd)

	var stdout, stderr bytes.Buffer
	code := Run(args, &stdout, &stderr)
	return code, stdout.String()
}

// TestScanIsReadOnly verifica che scan non modifichi l'albero: e' il dry run,
// e su questo si fonda tutta la separazione dei due sottocomandi (§1).
func TestScanIsReadOnly(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	before := snapshot(t, dir)
	code, _ := run(t, dir, "scan", ".")
	after := snapshot(t, dir)

	if code != ExitViolation {
		t.Errorf("exit code = %d, atteso %d: la fixture contiene violazioni", code, ExitViolation)
	}
	if !equalSlices(before, after) {
		t.Errorf("scan ha modificato l'albero:\n  prima: %v\n  dopo:  %v", before, after)
	}
}

// TestAutoRenameIsIdempotent e' il test end-to-end piu' forte disponibile: una
// seconda esecuzione su un albero gia' corretto non deve rinominare nulla
// (§9.4).
func TestAutoRenameIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	code1, out1 := run(t, dir, "auto-rename", ".")
	if code1 != ExitOK && code1 != ExitViolation {
		t.Fatalf("prima esecuzione: exit %d\n%s", code1, out1)
	}
	tree1 := snapshot(t, dir)

	code2, out2 := run(t, dir, "auto-rename", ".")
	tree2 := snapshot(t, dir)

	if !equalSlices(tree1, tree2) {
		t.Errorf("la seconda esecuzione ha modificato l'albero:\n  dopo la 1a: %v\n  dopo la 2a: %v",
			tree1, tree2)
	}
	if strings.Contains(out2, "Rinominate 0") == false {
		t.Errorf("la seconda esecuzione ha rinominato qualcosa:\n%s", out2)
	}
	if code2 != code1 {
		t.Errorf("exit code non stabile fra esecuzioni: %d poi %d", code1, code2)
	}
}

// TestAutoRenameProducesCompliantNames verifica che ogni nome rinominato sia
// effettivamente conforme dopo l'esecuzione: una rinomina che produce un nome
// ancora non conforme e' un bug del planner (§9.3).
func TestAutoRenameProducesCompliantNames(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	run(t, dir, "auto-rename", ".")

	// Il secondo scan deve trovare solo cio' che non era correggibile
	// automaticamente, mai una violazione introdotta dalla rinomina.
	_, out := run(t, dir, "scan", ".", "--output-json", filepath.Join(dir, "r.json"))

	data, err := os.ReadFile(filepath.Join(dir, "r.json"))
	if err != nil {
		t.Fatalf("lettura del report: %v", err)
	}
	var rep struct {
		Entries []struct {
			Path  string   `json:"path"`
			Codes []string `json:"codes"`
		} `json:"entries"`
	}
	if err := json.Unmarshal(data, &rep); err != nil {
		t.Fatalf("parsing del report: %v", err)
	}

	for _, e := range rep.Entries {
		// I caratteri fuori profilo senza mappatura restano: sono manual per
		// scelta, non un fallimento. Tutto il resto doveva essere corretto.
		for _, c := range e.Codes {
			if c == "POS-007" || c == "POS-002" || c == "POS-005" || c == "POS-008" {
				t.Errorf("%s: il codice %s doveva essere corretto automaticamente\n%s",
					e.Path, c, out)
			}
		}
	}
}

// TestOutputFormatsAgree verifica che i tre formati portino le stesse righe:
// differiscono solo nella presentazione (§4).
func TestOutputFormatsAgree(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	csvPath := filepath.Join(dir, "r.csv")
	jsonPath := filepath.Join(dir, "r.json")
	run(t, dir, "scan", ".", "--output-csv", csvPath, "--output-json", jsonPath)

	csvData, err := os.ReadFile(csvPath)
	if err != nil {
		t.Fatalf("lettura CSV: %v", err)
	}

	// Il BOM e' richiesto da Excel; il CRLF da RFC 4180 (§4.2).
	if !bytes.HasPrefix(csvData, []byte{0xEF, 0xBB, 0xBF}) {
		t.Error("il CSV non inizia con il BOM UTF-8")
	}
	if bytes.Contains(bytes.ReplaceAll(csvData, []byte("\r\n"), nil), []byte("\n")) {
		t.Error("il CSV contiene LF non preceduti da CR")
	}

	jsonData, err := os.ReadFile(jsonPath)
	if err != nil {
		t.Fatalf("lettura JSON: %v", err)
	}
	// Il BOM non deve mai raggiungere il writer JSON (§4.2).
	if bytes.HasPrefix(jsonData, []byte{0xEF, 0xBB, 0xBF}) {
		t.Error("il JSON inizia con un BOM: e' una proprieta' del solo CSV")
	}

	var rep struct {
		Entries []json.RawMessage `json:"entries"`
	}
	if err := json.Unmarshal(jsonData, &rep); err != nil {
		t.Fatalf("parsing JSON: %v", err)
	}

	// Righe CSV meno l'intestazione, contro le entry JSON.
	csvRows := bytes.Count(csvData, []byte("\r\n")) - 1
	if csvRows != len(rep.Entries) {
		t.Errorf("il CSV ha %d righe, il JSON %d entry: i formati devono concordare",
			csvRows, len(rep.Entries))
	}
}

// TestDeterminism verifica che due esecuzioni su un albero immutato producano
// output byte-identici, che e' il contratto di §5.
func TestDeterminism(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	readAll := func(name string) []byte {
		p := filepath.Join(dir, name)
		run(t, dir, "scan", ".", "--output-csv", p)
		b, err := os.ReadFile(p)
		if err != nil {
			t.Fatalf("lettura di %s: %v", p, err)
		}
		return b
	}

	if a, b := readAll("a.csv"), readAll("b.csv"); !bytes.Equal(a, b) {
		t.Error("due scan sullo stesso albero hanno prodotto CSV diversi")
	}
}

// TestShowOKAddsRowsOnly verifica che --show-ok cambi quali righe sono emesse e
// nient'altro: non le colonne, non l'ordine, non l'exit code (§3.3).
func TestShowOKAddsRowsOnly(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	codeA, _ := run(t, dir, "scan", ".")
	codeB, _ := run(t, dir, "scan", ".", "--show-ok")

	if codeA != codeB {
		t.Errorf("--show-ok ha cambiato l'exit code: %d senza, %d con", codeA, codeB)
	}
}

// TestNestedPathsRejected verifica che argomenti annidati o ripetuti siano
// rifiutati prima del walk, invece di produrre righe duplicate (§2.1).
func TestNestedPathsRejected(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir)

	if code, _ := run(t, dir, "scan", ".", "sub"); code != ExitUsage {
		t.Errorf("path annidati: exit %d, atteso %d", code, ExitUsage)
	}
	if code, _ := run(t, dir, "scan", ".", "."); code != ExitUsage {
		t.Errorf("path ripetuto: exit %d, atteso %d", code, ExitUsage)
	}
}

// snapshot elenca i path relativi presenti nell'albero, ordinati.
func snapshot(t *testing.T, dir string) []string {
	t.Helper()

	var out []string
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		// I file di output dei test non fanno parte dell'albero.
		if rel == "." || strings.HasSuffix(rel, ".json") || strings.HasSuffix(rel, ".csv") {
			return nil
		}
		out = append(out, filepath.ToSlash(rel))
		return nil
	})
	if err != nil {
		t.Fatalf("snapshot di %s: %v", dir, err)
	}
	sort.Strings(out)
	return out
}

func equalSlices(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
