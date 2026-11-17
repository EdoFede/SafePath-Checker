package rename

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

// Journal registra ogni rinomina riuscita, in append, subito dopo l'operazione.
//
// E' un ausilio al recupero e una traccia di audit, non un input
// dell'esecuzione successiva: auto-rename ri-deriva sempre tutto dal
// filesystem (§9.4). Va archiviato insieme al report, perche' insieme
// documentano cio' che l'esecuzione intendeva fare e cio' che ha fatto davvero.
type Journal struct {
	f *os.File
}

// JournalEntry e' una riga del journal.
type JournalEntry struct {
	Timestamp string `json:"timestamp"` // UTC, RFC 3339
	Dir       string `json:"dir"`
	OldName   string `json:"old_name"`
	NewName   string `json:"new_name"`
}

// OpenJournal apre il journal in append, creandolo se non esiste.
func OpenJournal(path string) (*Journal, error) {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, fmt.Errorf("apertura del journal %s: %w", path, err)
	}
	return &Journal{f: f}, nil
}

// Record annota una rinomina riuscita e forza la scrittura su disco: un journal
// non sincronizzato non sopravvive al crash da cui deve proteggere.
func (j *Journal) Record(dir, oldName, newName string) error {
	if j == nil || j.f == nil {
		return nil
	}

	line, err := json.Marshal(JournalEntry{
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Dir:       dir,
		OldName:   oldName,
		NewName:   newName,
	})
	if err != nil {
		return fmt.Errorf("serializzazione della riga di journal: %w", err)
	}

	if _, err := j.f.Write(append(line, '\n')); err != nil {
		return fmt.Errorf("scrittura del journal: %w", err)
	}
	return j.f.Sync()
}

// Close chiude il journal.
func (j *Journal) Close() error {
	if j == nil || j.f == nil {
		return nil
	}
	return j.f.Close()
}
