package report

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"os"
	"strings"
)

// utf8BOM e' richiesto da Excel: senza, UTF-8 viene letto come codepage ANSI di
// sistema e ogni nome accentato viene storpiato — esattamente i nomi che questo
// tool esiste per trovare (§4.2).
var utf8BOM = []byte{0xEF, 0xBB, 0xBF}

// WriteCSV scrive il report in CSV secondo RFC 4180 (§4.2).
//
// BOM e CRLF sono proprieta' del solo writer CSV e non devono raggiungere JSON,
// manifest o console. Il file e' scritto in modalita' binaria con il fine riga
// applicato esplicitamente, mai lasciato alla piattaforma (§5).
func WriteCSV(path string, r *Report) error {
	var buf bytes.Buffer
	buf.Write(utf8BOM)

	w := csv.NewWriter(&buf)
	w.UseCRLF = true

	if err := w.Write(csvHeader(r)); err != nil {
		return fmt.Errorf("scrittura dell'intestazione CSV: %w", err)
	}
	for _, row := range r.Rows {
		if err := w.Write(csvRow(row, r)); err != nil {
			return fmt.Errorf("scrittura di una riga CSV: %w", err)
		}
	}

	w.Flush()
	if err := w.Error(); err != nil {
		return fmt.Errorf("serializzazione CSV: %w", err)
	}

	if err := os.WriteFile(path, buf.Bytes(), 0o644); err != nil {
		return fmt.Errorf("scrittura di %s: %w", path, err)
	}
	return nil
}

// csvHeader costruisce l'intestazione. Il set di colonne non varia con i dati:
// --show-ok aggiunge righe, mai colonne. excluded_by e' l'unica eccezione ed e'
// appesa in fondo, cosi' che il prefisso resti stabile per un consumatore che
// legge le colonne per posizione (§4.2).
func csvHeader(r *Report) []string {
	h := []string{"root", "path", "type", "status", "codes", "detail"}
	if r.WithActions {
		h = append(h, "action", "new_path", "outcome", "outcome_detail")
	}
	if r.Options.ShowExcluded {
		h = append(h, "excluded_by")
	}
	return h
}

// csvRow serializza una riga. I valori vuoti restano campi vuoti, mai "NULL"
// o "-", e i codici multipli sono separati da spazio dentro un solo campo.
func csvRow(row Row, r *Report) []string {
	out := []string{
		row.Root,
		row.Path,
		row.Type,
		row.Status,
		strings.Join(row.Codes, " "),
		row.Detail,
	}
	if r.WithActions {
		out = append(out, string(row.Action), row.NewPath, string(row.Outcome), row.OutcomeDetail)
	}
	if r.Options.ShowExcluded {
		out = append(out, row.ExcludedBy)
	}
	return out
}
