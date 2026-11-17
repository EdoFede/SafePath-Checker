package rename

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// touch crea un file vuoto in dir.
func touch(t *testing.T, dir, name string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
		t.Fatalf("creazione di %s: %v", name, err)
	}
}

// exists riporta se un nome esiste, con il case esatto dato.
//
// os.Lstat non basta su un filesystem case-insensitive: stat("bilancio.xlsx")
// riesce anche quando il file e' ancora "Bilancio.xlsx" (§9.3). Serve rileggere
// la directory e confrontare i nomi.
func exists(t *testing.T, dir, name string) bool {
	t.Helper()
	names, err := FSRenamer{}.List(dir)
	if err != nil {
		t.Fatalf("lettura di %s: %v", dir, err)
	}
	for _, n := range names {
		if n == name {
			return true
		}
	}
	return false
}

// TestCaseOnlyRename verifica la rinomina che cambia solo il case, che su
// NTFS, APFS e HFS+ e' rifiutata, ignorata o accettata a seconda del
// filesystem: il doppio passaggio la rende affidabile ovunque (§8.1).
func TestCaseOnlyRename(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "Bilancio.xlsx")

	if err := (FSRenamer{}).Rename(dir, "Bilancio.xlsx", "bilancio.xlsx"); err != nil {
		t.Fatalf("rinomina case-only: %v", err)
	}

	if !exists(t, dir, "bilancio.xlsx") {
		t.Error("il nome minuscolo non risulta presente dopo la rinomina")
	}
	if exists(t, dir, "Bilancio.xlsx") {
		t.Error("il nome originale risulta ancora presente")
	}
}

// TestNoTempLeftBehind verifica che una rinomina case-only riuscita non lasci
// temporanei: un residuo inquinerebbe il report successivo (§8.1).
func TestNoTempLeftBehind(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "Bilancio.xlsx")

	if err := (FSRenamer{}).Rename(dir, "Bilancio.xlsx", "bilancio.xlsx"); err != nil {
		t.Fatalf("rinomina: %v", err)
	}

	names, _ := FSRenamer{}.List(dir)
	for _, n := range names {
		if strings.Contains(n, TempPrefix) {
			t.Errorf("temporaneo rimasto sul disco: %q", n)
		}
	}
}

// TestTempNameIsDeterministic verifica che il nome temporaneo sia derivato dal
// nome di destinazione: e' cio' che permette a un'esecuzione andata in crash di
// essere ripresa e al residuo di essere riconosciuto (§8.1).
func TestTempNameIsDeterministic(t *testing.T) {
	a := TempName("bilancio.xlsx")
	b := TempName("bilancio.xlsx")
	if a != b {
		t.Errorf("TempName non e' deterministico: %q poi %q", a, b)
	}
	if TempName("altro.xlsx") == a {
		t.Error("destinazioni diverse producono lo stesso temporaneo")
	}
	if !strings.Contains(a, TempPrefix) {
		t.Errorf("il temporaneo %q non porta il prefisso riconoscibile %q", a, TempPrefix)
	}
}

// TestOrphanRecovery verifica il recupero di un temporaneo lasciato da
// un'esecuzione interrotta (§8.1, §9.4).
func TestOrphanRecovery(t *testing.T) {
	dir := t.TempDir()
	tmpName := TempName("bilancio.xlsx")
	touch(t, dir, tmpName)

	orphans, err := FindOrphans(dir)
	if err != nil {
		t.Fatalf("ricerca dei temporanei: %v", err)
	}
	if len(orphans) != 1 {
		t.Fatalf("trovati %d temporanei, atteso 1", len(orphans))
	}
	if orphans[0].Target != "bilancio.xlsx" {
		t.Errorf("destinazione ricavata = %q, attesa %q", orphans[0].Target, "bilancio.xlsx")
	}

	if err := RecoverOrphan(orphans[0]); err != nil {
		t.Fatalf("recupero: %v", err)
	}
	if !exists(t, dir, "bilancio.xlsx") {
		t.Error("il temporaneo non e' stato portato al nome di destinazione")
	}
}

// TestOrphanRecoveryRefusesOccupiedTarget verifica che il recupero non
// sovrascriva una destinazione gia' occupata: rimuovere il temporaneo o
// sovrascrivere il file sono decisioni che il tool non prende da solo.
func TestOrphanRecoveryRefusesOccupiedTarget(t *testing.T) {
	dir := t.TempDir()
	touch(t, dir, "bilancio.xlsx")
	tmpName := TempName("bilancio.xlsx")
	touch(t, dir, tmpName)

	orphans, err := FindOrphans(dir)
	if err != nil || len(orphans) != 1 {
		t.Fatalf("ricerca dei temporanei: %v (trovati %d)", err, len(orphans))
	}

	if err := RecoverOrphan(orphans[0]); err == nil {
		t.Error("il recupero ha sovrascritto una destinazione occupata")
	}
	if !exists(t, dir, tmpName) {
		t.Error("il temporaneo e' stato rimosso invece di essere lasciato al suo posto")
	}
}

// TestJournalRecordsRenames verifica che il journal annoti le rinomine: e' un
// ausilio al recupero e una traccia di audit, da archiviare insieme al report
// (§9.4).
func TestJournalRecordsRenames(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "journal.jsonl")

	j, err := OpenJournal(path)
	if err != nil {
		t.Fatalf("apertura del journal: %v", err)
	}
	if err := j.Record("/alberi/a", "Vecchio.pdf", "Nuovo.pdf"); err != nil {
		t.Fatalf("scrittura: %v", err)
	}
	j.Close()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("lettura del journal: %v", err)
	}
	for _, want := range []string{"Vecchio.pdf", "Nuovo.pdf", "/alberi/a"} {
		if !strings.Contains(string(data), want) {
			t.Errorf("il journal non contiene %q:\n%s", want, data)
		}
	}
}
