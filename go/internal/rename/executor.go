package rename

import (
	"errors"
	"fmt"
	"path/filepath"
	"sort"

	"github.com/EdoFede/safepath-checker/go/internal/planner"
	"github.com/EdoFede/safepath-checker/go/internal/rules"
	"github.com/EdoFede/safepath-checker/go/internal/walker"
)

// ErrDrift segnala che una directory e' cambiata sotto il tool durante
// l'esecuzione. Vale exit 4, che prevale su exit 1: la deriva significa che il
// tool non puo' garantire cio' che ha fatto, e questo conta piu' del numero di
// violazioni rimaste (§12).
var ErrDrift = errors.New("la directory e' cambiata durante l'esecuzione")

// Result e' l'esito di una rinomina per una singola entry.
type Result struct {
	RelPath string // path relativo originale
	NewPath string // path relativo risultante, vuoto se non rinominata
	Action  planner.Action
	Outcome string
	Detail  string
	Unmappa []rune
}

// Executor applica le rinomine mentre il walk discende.
type Executor struct {
	Renamer Renamer
	Journal *Journal

	// Drift registra se e' stata rilevata una deriva in una qualsiasi
	// directory: determina l'exit code finale.
	Drift bool

	results  map[string]*Result
	unmapped *planner.UnmappedReport
}

// NewExecutor costruisce un executor sul backend dato.
func NewExecutor(r Renamer, j *Journal) *Executor {
	return &Executor{
		Renamer:  r,
		Journal:  j,
		results:  make(map[string]*Result),
		unmapped: planner.NewUnmappedReport(),
	}
}

// Results restituisce gli esiti indicizzati per path relativo originale.
func (e *Executor) Results() map[string]*Result { return e.results }

// Unmapped restituisce i caratteri privi di sostituzione incontrati.
func (e *Executor) Unmapped() *planner.UnmappedReport { return e.unmapped }

// ProcessDir e' il DirHook passato al walker: esegue i passi 3..6 del ciclo
// per-directory (§9.1) e restituisce le entry aggiornate con i nomi definitivi,
// cosi' che il walk discenda sotto quelli.
func (e *Executor) ProcessDir(dirAbs string, entries []walker.Entry) ([]walker.Entry, error) {
	// Il listing vivo, riletto adesso: il controllo di collisione non deve mai
	// girare su una copia in cache, perche' il file che verrebbe distrutto e'
	// uno che il tool non ha mai guardato (§8.2, §9.2).
	live, err := e.Renamer.List(dirAbs)
	if err != nil {
		return entries, nil // directory illeggibile: il walker l'ha gia' segnata
	}

	if e.hasDrift(entries, live) {
		return e.abortDir(entries), nil
	}

	candidates, kinds := renameCandidates(entries)
	if len(candidates) == 0 {
		return entries, nil
	}

	liveKeys := collisionKeys(live)
	ops := planner.Plan(candidates, kinds, func(key string) bool { return liveKeys[key] })

	byName := make(map[string]planner.Operation, len(ops))
	for _, op := range ops {
		byName[op.Name] = op
		e.unmapped.Add(op.Unmappa)
	}

	renamed := e.applyRenames(dirAbs, entries, byName)

	// La verifica avviene su una sola ri-lettura della directory a fine
	// rinomine: e' accettabile e piu' economica di una ri-lettura per entry,
	// purche' le conclusioni per entry siano tratte da quel listing (§9.3).
	if len(renamed) > 0 {
		e.verify(dirAbs, renamed)
	}

	return e.updateEntries(entries, byName), nil
}

// hasDrift confronta il listing su cui il walker ha deciso con quello vivo.
//
// Una divergenza significa che qualcuno ha modificato la directory fra la
// lettura e adesso: la finestra TOCTOU non e' chiudibile, va rilevata (§9.2).
func (e *Executor) hasDrift(entries []walker.Entry, live []string) bool {
	seen := make(map[string]bool, len(live))
	for _, n := range live {
		seen[rules.ToNFC(n)] = true
	}

	for _, en := range entries {
		if en.Status == walker.StatusSkipped {
			continue
		}
		if !seen[rules.ToNFC(en.Name())] {
			return true
		}
	}
	return false
}

// abortDir abbandona la directory corrente segnando ogni entry come fallita, e
// prosegue con il resto dell'albero: una directory volatile non e' un motivo
// per abbandonare un'esecuzione su un albero grande, ma e' un motivo per
// lasciare quella directory in pace (§9.2).
func (e *Executor) abortDir(entries []walker.Entry) []walker.Entry {
	e.Drift = true

	for _, en := range entries {
		e.results[en.RelPath] = &Result{
			RelPath: en.RelPath,
			Action:  planner.Action("failed"),
			Outcome: "error",
			Detail:  "directory modificata durante l'esecuzione: nessuna rinomina tentata",
		}
	}
	return entries
}

// renameCandidates seleziona le entry rinominabili: non escluse, non saltate.
//
// Un'entry esclusa non viene mai rinominata, nemmeno come effetto collaterale,
// ma resta occupante ai fini delle collisioni: esclusa significa "non
// toccare", non "non esiste" (§2.3).
func renameCandidates(entries []walker.Entry) ([]string, map[string]rules.Kind) {
	names := make([]string, 0, len(entries))
	kinds := make(map[string]rules.Kind, len(entries))

	for _, en := range entries {
		if en.Status == walker.StatusExcluded || en.Status == walker.StatusSkipped {
			continue
		}
		// Un nome non decodificabile non permette di costruire una
		// destinazione: e' manual, non un tentativo alla cieca (§7.1).
		if !en.ValidUTF8 {
			continue
		}
		names = append(names, en.Name())
		kinds[en.Name()] = en.Kind
	}

	sort.Slice(names, func(i, j int) bool {
		return rules.ToNFC(names[i]) < rules.ToNFC(names[j])
	})
	return names, kinds
}

// collisionKeys costruisce l'insieme delle chiavi occupate nel listing vivo.
func collisionKeys(live []string) map[string]bool {
	keys := make(map[string]bool, len(live))
	for _, n := range live {
		keys[rules.CollisionKey(n)] = true
	}
	return keys
}

// applyRenames esegue le rinomine decise e restituisce le coppie riuscite.
func (e *Executor) applyRenames(dirAbs string, entries []walker.Entry, byName map[string]planner.Operation) map[string]string {
	renamed := make(map[string]string)

	for _, en := range entries {
		if en.Status == walker.StatusExcluded || en.Status == walker.StatusSkipped {
			e.results[en.RelPath] = &Result{
				RelPath: en.RelPath, Action: planner.ActionNone, Outcome: "skipped",
				Detail: "entry esclusa o saltata: non viene rinominata",
			}
			continue
		}
		if !en.ValidUTF8 {
			e.results[en.RelPath] = &Result{
				RelPath: en.RelPath, Action: planner.ActionManual, Outcome: "skipped",
				Detail: "nome non decodificabile come UTF-8: destinazione non costruibile",
			}
			continue
		}

		op, ok := byName[en.Name()]
		if !ok || op.Action == planner.ActionNone {
			e.results[en.RelPath] = &Result{
				RelPath: en.RelPath, Action: planner.ActionNone, Outcome: "unchanged",
				Detail: "entry conforme: nessuna azione necessaria",
			}
			continue
		}
		if op.Action == planner.ActionManual {
			e.results[en.RelPath] = &Result{
				RelPath: en.RelPath, Action: planner.ActionManual, Outcome: "skipped",
				Detail: op.Reason, Unmappa: op.Unmappa,
			}
			continue
		}

		if err := e.Renamer.Rename(dirAbs, en.Name(), op.Target); err != nil {
			// Un file bloccato o un rifiuto del filesystem e' riportato e
			// l'esecuzione prosegue; non si ritenta in ciclo (§8.4).
			e.results[en.RelPath] = &Result{
				RelPath: en.RelPath, Action: planner.Action("failed"), Outcome: "error",
				Detail: fmt.Sprintf("rinomina rifiutata dal filesystem: %v", err),
			}
			continue
		}

		if err := e.Journal.Record(dirAbs, en.Name(), op.Target); err != nil {
			// Il journal e' un ausilio, non un vincolo: il suo fallimento non
			// annulla una rinomina gia' avvenuta.
			_ = err
		}

		renamed[en.Name()] = op.Target
		e.results[en.RelPath] = &Result{
			RelPath: en.RelPath,
			NewPath: replaceLast(en.RelPath, op.Target),
			Action:  planner.ActionRename,
			Outcome: "ok",
			Detail:  "rinominata",
		}
	}
	return renamed
}

// verify conferma le rinomine rileggendo la directory (§9.3).
//
// Il ritorno positivo di rename() non e' una prova: le rinomine case-only sono
// ignorate in silenzio da alcuni filesystem, una normalizzazione NFC puo'
// essere ri-decomposta da un client HFS+, e un filesystem di rete puo'
// confermare un'operazione che non ha eseguito.
func (e *Executor) verify(dirAbs string, renamed map[string]string) {
	after, err := e.Renamer.List(dirAbs)
	if err != nil {
		for old := range renamed {
			e.markVerifyFailure(old, fmt.Sprintf("ri-lettura della directory fallita: %v", err))
		}
		return
	}

	// Il confronto e' sulle forme NFC, byte per byte.
	present := make(map[string]bool, len(after))
	for _, n := range after {
		present[rules.ToNFC(n)] = true
	}

	for old, target := range renamed {
		switch {
		case !present[rules.ToNFC(target)]:
			e.markVerifyFailure(old, fmt.Sprintf("il nome di destinazione %q non risulta presente dopo la rinomina", target))
		case present[rules.ToNFC(old)] && rules.CollisionKey(old) != rules.CollisionKey(target):
			e.markVerifyFailure(old, fmt.Sprintf("il nome originale %q risulta ancora presente", old))
		default:
			// Una rinomina che ha prodotto un nome ancora non conforme e' un
			// bug del planner, e il report deve mostrarlo invece di nasconderlo.
			if codes := rules.ValidateComponent(target, rules.KindFile); len(codes) > 0 {
				e.markVerifyFailure(old, fmt.Sprintf("il nome risultante %q non e' conforme: %v", target, codes))
			}
		}
	}
}

// markVerifyFailure declassa a errore l'esito di una rinomina non confermata.
//
// Non si ritenta mai automaticamente: se il filesystem non ha fatto cio' che ha
// dichiarato, una seconda chiamata identica non ha piu' probabilita' di
// riuscire, e il tool non sa piu' in che stato si trova (§9.3).
func (e *Executor) markVerifyFailure(oldName, reason string) {
	for _, res := range e.results {
		if res.Action == planner.ActionRename && lastComponent(res.RelPath) == oldName {
			res.Outcome = "error"
			res.Detail = reason
			return
		}
	}
}

// updateEntries riscrive i path delle entry rinominate, cosi' che il walker
// discenda sotto i nomi definitivi (§9.1).
//
// Una directory che non e' stata rinominata resta con il nome vecchio e il suo
// sottoalbero viene comunque esaminato: un padre non riparabile non esenta i
// figli dall'essere controllati.
func (e *Executor) updateEntries(entries []walker.Entry, byName map[string]planner.Operation) []walker.Entry {
	out := make([]walker.Entry, 0, len(entries))

	for _, en := range entries {
		res, ok := e.results[en.RelPath]
		if ok && res.Action == planner.ActionRename && res.Outcome == "ok" {
			// Anche il path assoluto va aggiornato: il walker scende su
			// quello, e il nome vecchio su disco non esiste piu'.
			en.SetAbsPath(filepath.Join(filepath.Dir(en.AbsPath()), lastComponent(res.NewPath)))

			// L'esito va indicizzato anche sotto il path nuovo: il report
			// legge le entry come il walk le restituisce, cioe' con il nome
			// definitivo, e senza questa chiave la rinomina non comparirebbe.
			e.results[res.NewPath] = res
			en.RelPath = res.NewPath
		}
		out = append(out, en)
	}
	return out
}

// replaceLast sostituisce il componente finale di un path relativo.
func replaceLast(relPath, newName string) string {
	for i := len(relPath) - 1; i >= 0; i-- {
		if relPath[i] == '/' {
			return relPath[:i+1] + newName
		}
	}
	return newName
}

// lastComponent restituisce il componente finale di un path relativo.
func lastComponent(relPath string) string {
	for i := len(relPath) - 1; i >= 0; i-- {
		if relPath[i] == '/' {
			return relPath[i+1:]
		}
	}
	return relPath
}
