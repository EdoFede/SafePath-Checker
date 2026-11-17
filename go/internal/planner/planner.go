// Package planner calcola i nomi di destinazione a partire dalle violazioni.
//
// Non accede al filesystem: le verifiche di disponibilita' di un nome sono
// iniettate dal chiamante come Lookup (Development guidelines §1, §8.2).
package planner

import (
	"fmt"
	"sort"
	"strings"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// Action e' la decisione del planner per un'entry (§3.2).
type Action string

const (
	ActionNone   Action = "none"   // entry gia' conforme
	ActionRename Action = "rename" // esiste un nome di destinazione conforme
	ActionManual Action = "manual" // non correggibile automaticamente
)

// Operation e' l'esito della pianificazione per una singola entry.
type Operation struct {
	Name    string // nome originale, come trovato su disco
	Target  string // nome di destinazione; valorizzato solo se Action == ActionRename
	Action  Action
	Reason  string // motivo in italiano, per outcome_detail quando Action == ActionManual
	Unmappa []rune // caratteri fuori profilo privi di sostituzione, per il riepilogo
}

// Lookup riporta se un nome e' gia' presente nella directory, con confronto
// case-insensitive sulla chiave di collisione.
//
// Deve interrogare il listing vivo della directory, mai una copia in cache: e'
// la mitigazione della finestra TOCTOU di §9.2, dove il file distrutto e' uno
// che il tool non ha mai guardato.
type Lookup func(collisionKey string) bool

// Plan calcola le operazioni per un intero listing di directory.
//
// names e' il listing gia' ordinato per byte order del nome NFC (§7.3, §8.3):
// l'ordine fissato e' cio' che rende deterministica l'assegnazione dei suffissi
// di collisione. kinds associa a ogni nome il suo tipo.
//
// exists interroga la directory viva e deve gia' tenere conto delle entry
// escluse, che restano occupanti anche se non vanno rinominate (§2.3).
func Plan(names []string, kinds map[string]rules.Kind, exists Lookup) []Operation {
	ops := make([]Operation, 0, len(names))

	// taken accumula le chiavi di collisione gia' impegnate in questo giro:
	// i nomi originali non ancora rinominati piu' le destinazioni assegnate.
	// Senza questo, due nomi che convergono sullo stesso target si
	// sovrascriverebbero a vicenda.
	taken := make(map[string]bool, len(names))
	for _, n := range names {
		taken[rules.CollisionKey(n)] = true
	}

	// Le collisioni case-insensitive gia' presenti nel listing di partenza.
	//
	// Solo i membri successivi al primo devono spostarsi: con l'ordine fissato
	// per byte order, il primo conserva il proprio nome e gli altri prendono il
	// suffisso, che e' la risoluzione deterministica di §8.3 e l'esempio della
	// tabella di rewrite di §9.
	colliding := rules.CheckCollisions(names)
	firstOfGroup := make(map[string]bool, len(names))

	for _, name := range names {
		kind := kinds[name]

		mustMove := false
		if colliding[name] {
			key := rules.CollisionKey(name)
			mustMove = firstOfGroup[key] // il primo del gruppo resta dov'e'
			firstOfGroup[key] = true
		}

		op := planOne(name, kind, mustMove, taken, exists)

		// La destinazione scelta impegna la sua chiave e libera quella del
		// nome originale, che dopo il rename non esistera' piu'.
		if op.Action == ActionRename {
			delete(taken, rules.CollisionKey(name))
			taken[rules.CollisionKey(op.Target)] = true
		}
		ops = append(ops, op)
	}
	return ops
}

// planOne calcola l'operazione per una singola entry.
func planOne(name string, kind rules.Kind, hasCollision bool, taken map[string]bool, exists Lookup) Operation {
	codes := rules.ValidateComponent(name, kind)
	if len(codes) == 0 && !hasCollision {
		return Operation{Name: name, Action: ActionNone}
	}

	candidate, unmapped := Remediate(name, kind)
	if len(unmapped) > 0 {
		return Operation{
			Name:    name,
			Action:  ActionManual,
			Reason:  fmt.Sprintf("caratteri fuori profilo senza sostituzione prevista: %s", formatRunes(unmapped)),
			Unmappa: unmapped,
		}
	}
	if candidate == "" {
		return Operation{
			Name:   name,
			Action: ActionManual,
			Reason: "la correzione non lascia alcun nome utilizzabile",
		}
	}

	// Il candidato deve essere libero: sia rispetto al listing corrente, sia
	// rispetto alla directory viva, che puo' contenere entry escluse.
	//
	// Quando la violazione e' la collisione stessa, il nome non puo' valere
	// come esenzione per se stesso: deve spostarsi su un nome distinto,
	// altrimenti resterebbe indefinitamente in conflitto con l'omonimo.
	self := name
	if hasCollision {
		self = ""
	}
	target, ok := resolveFree(candidate, self, kind, taken, exists)
	if !ok {
		return Operation{
			Name:   name,
			Action: ActionManual,
			Reason: "nessun nome conforme disponibile: troppe collisioni o limite di lunghezza",
		}
	}

	// Un target identico all'originale significa che le violazioni rilevate
	// non sono correggibili per costruzione (per esempio una collisione gia'
	// risolta altrove): niente da fare.
	if target == name {
		return Operation{Name: name, Action: ActionNone}
	}

	return Operation{Name: name, Target: target, Action: ActionRename}
}

// resolveFree cerca il primo nome disponibile a partire da candidate,
// aggiungendo se necessario un suffisso numerico progressivo (§8.3).
//
// Il suffisso e' inserito prima dell'estensione ("Bilancio_1.xlsx", non
// "Bilancio.xlsx_1") e il risultato e' rivalidato: il suffisso puo' spingere il
// nome oltre il limite di lunghezza.
//
// Restituisce ok=false se nessun nome conforme e' disponibile: in quel caso
// l'entry e' manual, mai troncata. Accorciare il nome di un documento e' una
// decisione che il tool non e' autorizzato a prendere (§8.3).
func resolveFree(candidate, original string, kind rules.Kind, taken map[string]bool, exists Lookup) (string, bool) {
	// Il nome originale non e' un ostacolo per se stesso: viene liberato dal
	// rename. Le altre chiavi impegnate sono invece vincolanti.
	self := rules.CollisionKey(original)

	free := func(n string) bool {
		k := rules.CollisionKey(n)
		if k != self && taken[k] {
			return false
		}
		if k != self && exists != nil && exists(k) {
			return false
		}
		return len(rules.ValidateComponent(n, kind)) == 0
	}

	if free(candidate) {
		return candidate, true
	}

	base, ext := rules.SplitExtension(candidate)
	// Il limite di tentativi tiene il caso patologico fuori da un ciclo
	// illimitato: oltre, l'entry e' legittimamente manual.
	for i := 1; i <= 999; i++ {
		suffixed := fmt.Sprintf("%s_%d%s", base, i, ext)
		if free(suffixed) {
			return suffixed, true
		}
	}
	return "", false
}

// formatRunes rende leggibile un elenco di caratteri nel messaggio di errore,
// con il code point accanto al glifo perche' molti sono invisibili o simili
// fra loro.
func formatRunes(rs []rune) string {
	parts := make([]string, 0, len(rs))
	for _, r := range rs {
		parts = append(parts, fmt.Sprintf("%q (U+%04X)", r, r))
	}
	return strings.Join(parts, ", ")
}

// UnmappedReport raccoglie i caratteri privi di sostituzione incontrati durante
// un'esecuzione, per il riepilogo finale (§4.1).
type UnmappedReport struct {
	counts map[rune]int
}

// NewUnmappedReport crea un accumulatore vuoto.
func NewUnmappedReport() *UnmappedReport {
	return &UnmappedReport{counts: make(map[rune]int)}
}

// Add registra i caratteri non mappati di un'operazione.
func (u *UnmappedReport) Add(rs []rune) {
	for _, r := range rs {
		u.counts[r]++
	}
}

// UnmappedChar e' una riga del riepilogo dei caratteri non mappati.
type UnmappedChar struct {
	Rune  rune
	Count int
}

// Chars restituisce i caratteri raccolti, ordinati per code point.
//
// L'ordinamento e' per code point e non per frequenza: il contratto di
// determinismo vieta di emettere l'iterazione di una mappa, e due esecuzioni
// con gli stessi conteggi devono produrre lo stesso ordine (§5).
func (u *UnmappedReport) Chars() []UnmappedChar {
	out := make([]UnmappedChar, 0, len(u.counts))
	for r, c := range u.counts {
		out = append(out, UnmappedChar{Rune: r, Count: c})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Rune < out[j].Rune })
	return out
}

// Empty riporta se non e' stato raccolto alcun carattere non mappato.
func (u *UnmappedReport) Empty() bool { return len(u.counts) == 0 }
