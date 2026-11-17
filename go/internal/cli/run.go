package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/EdoFede/safepath-checker/go/internal/planner"
	"github.com/EdoFede/safepath-checker/go/internal/rename"
	"github.com/EdoFede/safepath-checker/go/internal/report"
	"github.com/EdoFede/safepath-checker/go/internal/rules"
	"github.com/EdoFede/safepath-checker/go/internal/walker"
)

// Version e' la versione del tool, sovrascrivibile al build con
// -ldflags "-X .../internal/cli.Version=x.y.z".
var Version = "dev"

// UnicodeVersion e' la versione delle tabelle Unicode contro cui il binario e'
// stato compilato. Compare nell'header del report: due esecuzioni con tabelle
// diverse non sono confrontabili (§6.1).
const UnicodeVersion = "15.0.0"

// Run esegue il comando e restituisce l'exit code.
//
// stdout riceve la tabella e il riepilogo; stderr diagnostica ed errori, cosi'
// che una redirezione catturi la sola tabella (§4.1).
func Run(args []string, stdout, stderr io.Writer) int {
	opts, err := Parse(args)
	if err != nil {
		fmt.Fprintf(stderr, "safepath: %v\n", err)
		fmt.Fprint(stderr, usage)
		return ExitUsage
	}

	matcher, err := walker.NewMatcher(opts.Exclude, opts.ExcludeRegex)
	if err != nil {
		// Un pattern non compilabile non viene mai trattato come stringa
		// letterale: e' exit 2 con il messaggio del compilatore (§2.3).
		fmt.Fprintf(stderr, "safepath: %v\n", err)
		return ExitUsage
	}

	rep := newReport(opts)

	var executor *rename.Executor
	if opts.Command == "auto-rename" {
		executor, err = prepareRename(opts, stderr)
		if err != nil {
			fmt.Fprintf(stderr, "safepath: %v\n", err)
			return ExitIO
		}
		defer executor.Journal.Close()
	}

	var allEntries []walker.Entry
	for _, p := range opts.Paths {
		entries, err := scanRoot(p, matcher, executor)
		if err != nil {
			// Una scan root illeggibile rende l'esecuzione priva di senso: e'
			// uno dei pochi errori che interrompono (§9.4).
			fmt.Fprintf(stderr, "safepath: %v\n", err)
			return ExitUsage
		}
		allEntries = append(allEntries, entries...)
	}

	buildRows(rep, allEntries, executor)
	rep.Sort()

	if err := emit(rep, allEntries, opts, stdout); err != nil {
		fmt.Fprintf(stderr, "safepath: %v\n", err)
		return ExitIO
	}

	return exitCode(rep, executor)
}

// newReport prepara l'intestazione, che e' cio' che rende un report
// riproducibile a distanza di mesi (§4.3).
func newReport(o *Options) *report.Report {
	return &report.Report{
		SchemaVersion:  report.SchemaVersion,
		RulesetVersion: rules.RulesetVersion,
		UnicodeVersion: UnicodeVersion,
		ToolVersion:    Version,
		Command:        o.Command,
		GeneratedAt:    time.Now().UTC().Format(time.RFC3339),
		Roots:          o.Paths,
		WithActions:    o.Command == "auto-rename",
		Options: report.Options{
			ShowOK:       o.ShowOK,
			ShowExcluded: o.ShowExcluded,
			Exclude:      o.Exclude,
			ExcludeRegex: o.ExcludeRegex,
		},
	}
}

// prepareRename costruisce l'executor e recupera i temporanei rimasti da
// un'esecuzione interrotta (§8.1, §9.4).
func prepareRename(o *Options, stderr io.Writer) (*rename.Executor, error) {
	for _, p := range o.Paths {
		orphans, err := rename.FindOrphans(p)
		if err != nil {
			return nil, err
		}
		for _, orph := range orphans {
			if err := rename.RecoverOrphan(orph); err != nil {
				fmt.Fprintf(stderr, "safepath: recupero non riuscito: %v\n", err)
				continue
			}
			fmt.Fprintf(stderr, "safepath: completato il temporaneo %q -> %q\n",
				orph.Name, orph.Target)
		}
	}

	// Nessun journal se non e' stato richiesto: creare un file non richiesto
	// nella directory di lavoro sarebbe una sorpresa. Il journal resta un
	// ausilio al recupero e una traccia di audit da archiviare insieme al
	// report (§9.4).
	if o.Journal == "" {
		return rename.NewExecutor(rename.FSRenamer{}, nil), nil
	}

	journal, err := rename.OpenJournal(o.Journal)
	if err != nil {
		return nil, err
	}
	return rename.NewExecutor(rename.FSRenamer{}, journal), nil
}

// scanRoot esegue il walk di una singola scan root.
func scanRoot(rootArg string, m *walker.Matcher, ex *rename.Executor) ([]walker.Entry, error) {
	abs, err := filepath.Abs(rootArg)
	if err != nil {
		return nil, fmt.Errorf("path non utilizzabile %q: %w", rootArg, err)
	}

	opts := walker.Options{Matcher: m}
	if ex != nil {
		opts.DirHook = ex.ProcessDir
	}
	return walker.Walk(rootArg, abs, opts)
}

// buildRows trasforma le entry in righe di report, applicando la validazione e,
// per auto-rename, gli esiti delle rinomine.
func buildRows(rep *report.Report, entries []walker.Entry, ex *rename.Executor) {
	// Le collisioni si valutano per directory: nomi in directory diverse non
	// competono (§5).
	collisions := collisionsByDir(entries)

	for _, e := range entries {
		rep.Summary.Examined++

		row := report.Row{
			Root: e.Root,
			Path: e.RelPath,
			Type: e.Type,
		}

		switch e.Status {
		case walker.StatusSkipped:
			// Cio' che il tool non ha potuto esaminare e' un finding: le righe
			// skipped sono sempre emesse, indipendentemente da --show-ok (§3.3).
			row.Status = string(walker.StatusSkipped)
			row.Detail = e.SkipReason
			rep.Summary.Skipped++

		case walker.StatusExcluded:
			row.Status = string(walker.StatusExcluded)
			row.Detail = string(e.ExcludedKind)
			row.ExcludedBy = e.ExcludedBy
			rep.Summary.Excluded++
			if !rep.Options.ShowExcluded {
				continue // nessuna riga senza il flag (§3.4)
			}

		default:
			// La validazione avviene sul path com'era prima della rinomina:
			// codes descrive sempre lo stato originale, anche a rinomina
			// riuscita. Un report i cui findings si svuotassero come effetto
			// collaterale della correzione sarebbe inutile come traccia di
			// audit; per vedere l'albero dopo la remediation si riesegue scan,
			// che e' esattamente a questo che serve (§3.2).
			validated := e.RelPath
			if res := resultFor(ex, e.RelPath); res != nil && res.RelPath != "" {
				validated = res.RelPath
			}
			row.Path = validated

			codes := rules.ValidatePath(rules.Target{
				RelPath:   validated,
				Kind:      e.Kind,
				ValidUTF8: e.ValidUTF8,
			})
			if collisions[e.RelPath] {
				codes = appendSorted(codes, rules.CodeUNQ001)
			}

			row.Codes = codes
			if len(codes) == 0 {
				row.Status = string(walker.StatusOK)
				rep.Summary.OK++
			} else {
				row.Status = string(walker.StatusViolation)
				row.Detail = describeCodes(codes)
				rep.Summary.Violations++
			}

			// I conteggi delle azioni precedono lo scarto delle righe ok:
			// --show-ok cambia quali righe sono emesse e nient'altro, non il
			// riepilogo ne' l'exit code (§3.3).
			if rep.WithActions {
				applyAction(&row, e, ex, rep)
			}
			if len(codes) == 0 && !rep.Options.ShowOK {
				continue // solo le righe non ok, per default (§3.3)
			}
			rep.Rows = append(rep.Rows, row)
			continue
		}

		if rep.WithActions {
			applyAction(&row, e, ex, rep)
		}
		rep.Rows = append(rep.Rows, row)
	}

	if ex != nil && !ex.Unmapped().Empty() {
		rep.Unmapped = ex.Unmapped().Chars()
	}
}

// resultFor recupera l'esito della rinomina di un'entry, se ce n'e' uno.
//
// L'executor indicizza ogni esito sia sotto il path originale sia sotto quello
// definitivo, perche' il walk restituisce le entry con il nome nuovo.
func resultFor(ex *rename.Executor, relPath string) *rename.Result {
	if ex == nil {
		return nil
	}
	return ex.Results()[relPath]
}

// applyAction riempie le colonne azione di una riga (§3.2).
//
// I codici continuano a descrivere lo stato originale anche a rinomina
// riuscita: il report documenta cio' che e' stato trovato, non cio' che resta.
func applyAction(row *report.Row, e walker.Entry, ex *rename.Executor, rep *report.Report) {
	if ex == nil {
		return
	}

	res := resultFor(ex, e.RelPath)
	if res == nil {
		row.Action = report.ActionNone
		row.Outcome = report.OutcomeUnchanged
		row.OutcomeDetail = "nessuna azione necessaria"
		return
	}

	row.Action = report.Action(res.Action)
	row.NewPath = res.NewPath
	row.Outcome = report.Outcome(res.Outcome)
	row.OutcomeDetail = res.Detail

	switch {
	case res.Action == planner.ActionRename && res.Outcome == "ok":
		rep.Summary.Renamed++
	case res.Action == planner.ActionManual:
		rep.Summary.Manual++
	case res.Outcome == "error":
		rep.Summary.Failed++
	}
}

// collisionsByDir individua le entry coinvolte in una collisione
// case-insensitive, confrontando solo nomi della stessa directory (§5).
func collisionsByDir(entries []walker.Entry) map[string]bool {
	byDir := make(map[string][]walker.Entry)
	for _, e := range entries {
		if e.Status == walker.StatusSkipped || e.Status == walker.StatusExcluded {
			continue
		}
		byDir[e.Root+"\x00"+dirOf(e.RelPath)] = append(byDir[e.Root+"\x00"+dirOf(e.RelPath)], e)
	}

	out := make(map[string]bool)
	for _, group := range byDir {
		names := make([]string, 0, len(group))
		for _, e := range group {
			names = append(names, e.Name())
		}
		colliding := rules.CheckCollisions(names)
		for _, e := range group {
			if colliding[e.Name()] {
				out[e.RelPath] = true
			}
		}
	}
	return out
}

// dirOf restituisce la porzione di directory di un path relativo.
func dirOf(relPath string) string {
	if i := strings.LastIndex(relPath, "/"); i >= 0 {
		return relPath[:i]
	}
	return ""
}

// appendSorted aggiunge un codice mantenendo l'ordine e senza duplicare.
func appendSorted(codes []string, code string) []string {
	for _, c := range codes {
		if c == code {
			return codes
		}
	}
	out := append(codes, code)
	for i := len(out) - 1; i > 0 && out[i-1] > out[i]; i-- {
		out[i-1], out[i] = out[i], out[i-1]
	}
	return out
}

// describeCodes compone la descrizione italiana della colonna detail. E' il
// campo umano: quello leggibile dalle macchine e' codes, che non va mai
// ricavato da qui (§3.1).
func describeCodes(codes []string) string {
	parts := make([]string, 0, len(codes))
	for _, c := range codes {
		parts = append(parts, rules.Describe(c))
	}
	return strings.Join(parts, "; ")
}

// emit produce la tabella su stdout e i file richiesti.
//
// La tabella e' sempre prodotta e nessun output su file la sopprime (§4).
func emit(rep *report.Report, entries []walker.Entry, o *Options, stdout io.Writer) error {
	consoleOpts := report.ConsoleOptions{Width: report.DefaultWidth}
	if f, ok := stdout.(*os.File); ok {
		consoleOpts = report.DetectConsoleOptions(f)
	}
	if err := report.WriteConsole(stdout, rep, consoleOpts); err != nil {
		return err
	}

	if o.OutputCSV != "" {
		if err := report.WriteCSV(o.OutputCSV, rep); err != nil {
			return err
		}
	}
	if o.OutputJSON != "" {
		if err := report.WriteJSON(o.OutputJSON, rep); err != nil {
			return err
		}
	}
	if o.EmitManifest != "" {
		if err := report.WriteManifest(o.EmitManifest, entries); err != nil {
			return err
		}
	}
	return nil
}

// exitCode determina l'exit code finale (§12).
//
// L'asimmetria su exit 1 e' voluta: scan riporta cio' che non va, quindi una
// qualsiasi violazione e' exit 1; auto-rename e' fatto per correggere, quindi
// un'esecuzione che ha riparato tutto esce 0. Exit 4 prevale su exit 1, perche'
// la deriva significa che il tool non puo' garantire cio' che ha fatto.
func exitCode(rep *report.Report, ex *rename.Executor) int {
	if ex != nil && ex.Drift {
		return ExitDrift
	}

	if rep.WithActions {
		if rep.HasBlocking() {
			return ExitViolation
		}
		return ExitOK
	}

	if rep.Summary.Violations > 0 {
		return ExitViolation
	}
	return ExitOK
}

const usage = `
Uso:
  safepath scan        [opzioni] <path>...
  safepath auto-rename [opzioni] <path>...

scan e' in sola lettura ed e' il dry run di auto-rename.

Opzioni:
  --show-ok                include nel report anche le voci conformi
  --exclude <glob>         esclude le voci che corrispondono al glob (ripetibile)
  --exclude-regex <re>     esclude le voci che corrispondono alla regex (ripetibile)
  --show-excluded          include nel report le voci escluse
  --output-csv <file>      scrive il report in CSV
  --output-json <file>     scrive il report in JSON
  --emit-manifest <file>   scrive il manifest JSONL delle voci
  --journal <file>         (solo auto-rename) registra le rinomine eseguite

Exit code:
  0 nulla da correggere   1 violazioni   2 argomenti non validi
  3 errore di I/O         4 deriva rilevata durante l'esecuzione
`
