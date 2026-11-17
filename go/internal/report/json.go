package report

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
)

// WriteJSON scrive il report come singolo documento JSON (§4.3).
//
// UTF-8 senza BOM, fine riga "\n", chiavi ordinate. I non-ASCII non vengono
// escapati: i nomi accentati devono restare leggibili nel file.
func WriteJSON(path string, r *Report) error {
	doc := map[string]any{
		"schema_version":  r.SchemaVersion,
		"ruleset_version": r.RulesetVersion,
		"unicode_version": r.UnicodeVersion,
		"tool_version":    r.ToolVersion,
		"command":         r.Command,
		"generated_at":    r.GeneratedAt,
		"roots":           r.Roots,
		"options":         jsonOptions(r.Options),
		"summary":         jsonSummary(r.Summary, r.WithActions),
		"entries":         jsonEntries(r),
	}

	// I caratteri non mappati sono un'informazione operativa: senza, l'utente
	// non sa quali righe aggiungere a charMap per rendere automatiche le
	// entry rimaste manual.
	if len(r.Unmapped) > 0 {
		doc["unmapped_chars"] = jsonUnmapped(r.Unmapped)
	}

	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false) // niente escape di & < >: i nomi restano leggibili
	enc.SetIndent("", "  ")

	// encoding/json ordina le chiavi delle mappe, che e' cio' che il contratto
	// di determinismo richiede (§5).
	if err := enc.Encode(doc); err != nil {
		return fmt.Errorf("serializzazione JSON: %w", err)
	}

	if err := os.WriteFile(path, buf.Bytes(), 0o644); err != nil {
		return fmt.Errorf("scrittura di %s: %w", path, err)
	}
	return nil
}

// jsonOptions serializza le opzioni di esclusione come date da riga di comando,
// non normalizzate, ciascuna nel proprio array: un glob e una regex che si
// somigliano non significano la stessa cosa (§4.3).
func jsonOptions(o Options) map[string]any {
	return map[string]any{
		"show_ok":       o.ShowOK,
		"show_excluded": o.ShowExcluded,
		"exclude":       nonNil(o.Exclude),
		"exclude_regex": nonNil(o.ExcludeRegex),
	}
}

func jsonSummary(s Summary, withActions bool) map[string]any {
	m := map[string]any{
		"examined":   s.Examined,
		"ok":         s.OK,
		"violations": s.Violations,
		"skipped":    s.Skipped,
		"excluded":   s.Excluded,
	}
	if withActions {
		m["renamed"] = s.Renamed
		m["failed"] = s.Failed
		m["manual"] = s.Manual
	}
	return m
}

// jsonEntries costruisce l'array delle entry, sempre presente anche se vuoto
// (§4.3).
func jsonEntries(r *Report) []map[string]any {
	out := make([]map[string]any, 0, len(r.Rows))

	for _, row := range r.Rows {
		e := map[string]any{
			"root":   row.Root,
			"path":   row.Path,
			"type":   row.Type,
			"status": row.Status,
			// codes e' un array, non una stringa: questo e' il formato per le
			// macchine, e l'appiattimento del CSV e' una concessione a un
			// formato testuale, non il modello (§4.3).
			"codes":  nonNil(row.Codes),
			"detail": row.Detail,
		}

		// I quattro campi azione esistono solo per auto-rename: assenti, non
		// nulli, sotto scan.
		if r.WithActions {
			e["action"] = string(row.Action)
			e["new_path"] = row.NewPath
			e["outcome"] = string(row.Outcome)
			e["outcome_detail"] = row.OutcomeDetail
		}

		// excluded_by solo sulle righe escluse e solo con --show-excluded.
		if r.Options.ShowExcluded && row.Status == "excluded" && row.ExcludedBy != "" {
			e["excluded_by"] = row.ExcludedBy
		}

		out = append(out, e)
	}
	return out
}

// jsonUnmapped serializza il riepilogo dei caratteri non mappati, gia' ordinato
// per code point dal planner.
func jsonUnmapped(chars []UnmappedChar) []map[string]any {
	out := make([]map[string]any, 0, len(chars))
	for _, c := range chars {
		out = append(out, map[string]any{
			"char":        string(c.Rune),
			"codepoint":   fmt.Sprintf("U+%04X", c.Rune),
			"occurrences": c.Count,
		})
	}
	return out
}

// nonNil garantisce un array JSON vuoto al posto di null: un consumatore che
// itera non deve dover distinguere i due casi.
func nonNil(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}
