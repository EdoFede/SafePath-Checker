// Package report accumula le righe e le serializza nei tre formati.
//
// Le righe non possono essere emesse mano a mano che il walk procede: escono
// ordinate e non in ordine di scoperta, quindi vanno accumulate, ordinate e
// solo allora emesse (Development guidelines §5).
package report

import (
	"sort"

	"github.com/EdoFede/safepath-checker/go/internal/planner"
)

// SchemaVersion identifica la forma del report. Compare nell'header ed e'
// confrontata dai test di parita' (§10).
const SchemaVersion = "1"

// UnmappedChar e' un carattere fuori profilo privo di sostituzione, con il
// numero di occorrenze incontrate. Alias del tipo del planner, che e' dove il
// dato viene prodotto.
type UnmappedChar = planner.UnmappedChar

// Outcome e' cio' che il filesystem ha confermato dopo la ri-lettura (§3.2).
type Outcome string

const (
	OutcomeOK        Outcome = "ok"
	OutcomeUnchanged Outcome = "unchanged"
	OutcomeError     Outcome = "error"
	OutcomeSkipped   Outcome = "skipped"
)

// Action e' cio' che il tool ha deciso di fare (§3.2).
type Action string

const (
	ActionRename Action = "rename"
	ActionNone   Action = "none"
	ActionManual Action = "manual"
	ActionFailed Action = "failed"
)

// Row e' una riga del report: una per entry, sempre, cosi' che il conteggio
// delle righe abbia significato (§3.1).
type Row struct {
	Root   string
	Path   string
	Type   string
	Status string
	Codes  []string
	Detail string

	// Colonne azione, solo per auto-rename (§3.2).
	NewPath       string
	Action        Action
	Outcome       Outcome
	OutcomeDetail string

	// ExcludedBy e' presente solo con --show-excluded (§3.4).
	ExcludedBy string
}

// Summary sono i conteggi del riepilogo di fine esecuzione (§4.1).
type Summary struct {
	Examined   int `json:"examined"`
	OK         int `json:"ok"`
	Violations int `json:"violations"`
	Skipped    int `json:"skipped"`
	Excluded   int `json:"excluded"`

	// Solo per auto-rename.
	Renamed int `json:"renamed,omitempty"`
	Failed  int `json:"failed,omitempty"`
	Manual  int `json:"manual,omitempty"`
}

// Options riporta le opzioni di invocazione nel report, cosi' che sia
// interpretabile a distanza di mesi (§4.3).
type Options struct {
	ShowOK       bool     `json:"show_ok"`
	ShowExcluded bool     `json:"show_excluded"`
	Exclude      []string `json:"exclude"`
	ExcludeRegex []string `json:"exclude_regex"`
}

// Report e' l'insieme completo di cio' che un'esecuzione produce.
type Report struct {
	SchemaVersion  string
	RulesetVersion string
	UnicodeVersion string
	ToolVersion    string
	Command        string // "scan" | "auto-rename"
	GeneratedAt    string // UTC, RFC 3339
	Roots          []string
	Options        Options
	Summary        Summary
	Rows           []Row

	// Unmapped sono i caratteri fuori profilo privi di sostituzione incontrati
	// durante l'esecuzione: e' il punto di partenza per estendere charMap.
	Unmapped []UnmappedChar

	// WithActions distingue le due forme del report. Le colonne azione sono
	// assenti, non nulle, sotto scan: la loro assenza e' il modo in cui un
	// consumatore distingue le due forme (§4.3).
	WithActions bool
}

// Sort ordina le righe secondo il contratto di determinismo: le root
// nell'ordine di riga di comando, e all'interno di ogni root il byte order del
// path (§5).
func (r *Report) Sort() {
	rootIndex := make(map[string]int, len(r.Roots))
	for i, root := range r.Roots {
		rootIndex[root] = i
	}

	sort.SliceStable(r.Rows, func(i, j int) bool {
		ri, rj := rootIndex[r.Rows[i].Root], rootIndex[r.Rows[j].Root]
		if ri != rj {
			return ri < rj
		}
		return r.Rows[i].Path < r.Rows[j].Path
	})
}

// HasBlocking riporta se restano violazioni non risolte, che e' cio' che
// distingue exit 0 da exit 1 per auto-rename: la domanda utile per uno script
// non e' "c'era qualcosa che non andava?" ma "c'e' ancora qualcosa?" (§12).
func (r *Report) HasBlocking() bool {
	for _, row := range r.Rows {
		if row.Action == ActionManual || row.Action == ActionFailed {
			return true
		}
	}
	return false
}
