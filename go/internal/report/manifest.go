package report

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"

	"github.com/EdoFede/safepath-checker/go/internal/walker"
)

// WriteManifest scrive la serializzazione JSONL di []Entry (§1).
//
// Il manifest e' un output opzionale e non fa parte del flusso normale: serve
// ad archiviare lo stato a cui un report si riferisce, a fare il diff fra due
// esecuzioni consecutive, ed e' il trasporto usato dai test di parita' (§10).
//
// Resta JSONL, non un documento unico come il report JSON: e' uno stream.
func WriteManifest(path string, entries []walker.Entry) error {
	var buf bytes.Buffer

	for _, e := range entries {
		line, err := json.Marshal(e)
		if err != nil {
			return fmt.Errorf("serializzazione del manifest: %w", err)
		}
		buf.Write(line)
		// Fine riga esplicito: mai lasciato alla piattaforma, il file va
		// scritto in modalita' binaria (§5).
		buf.WriteByte('\n')
	}

	if err := os.WriteFile(path, buf.Bytes(), 0o644); err != nil {
		return fmt.Errorf("scrittura di %s: %w", path, err)
	}
	return nil
}
