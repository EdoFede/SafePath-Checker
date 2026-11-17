// Package cli implementa il parsing degli argomenti e i due sottocomandi.
package cli

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
)

// Exit codes (Development guidelines §12).
//
// Le violazioni sono dati, non errori: exit 1 deve restare distinguibile da un
// crash perche' il tool sia scriptabile.
const (
	ExitOK        = 0 // esecuzione completata, nulla da correggere
	ExitViolation = 1 // violazioni trovate (scan) o rimaste (auto-rename)
	ExitUsage     = 2 // argomenti non validi o path inutilizzabile
	ExitIO        = 3 // errore di I/O nel walk o nella scrittura di un output
	ExitDrift     = 4 // una directory e' cambiata sotto il tool (§9.2)
)

// Options raccoglie le opzioni di invocazione.
type Options struct {
	Command string   // "scan" | "auto-rename"
	Paths   []string // argomenti di path, nell'ordine dato

	ShowOK       bool
	ShowExcluded bool
	Exclude      []string
	ExcludeRegex []string

	OutputCSV    string
	OutputJSON   string
	EmitManifest string

	// Journal e' il path del journal delle rinomine (§9.4). Vuoto significa
	// nessun journal: il file non viene creato di default, perche' un output
	// non richiesto nella directory di lavoro e' una sorpresa, non una
	// funzionalita'. Va archiviato insieme al report.
	Journal string
}

// usageError segnala un errore di riga di comando, che vale exit 2.
type usageError struct{ msg string }

func (e *usageError) Error() string { return e.msg }

func usagef(format string, args ...any) error {
	return &usageError{msg: fmt.Sprintf(format, args...)}
}

// IsUsageError riporta se l'errore va tradotto in exit 2.
func IsUsageError(err error) bool {
	var ue *usageError
	return errors.As(err, &ue)
}

// Parse interpreta gli argomenti di riga di comando.
//
// Una seconda occorrenza della stessa opzione di output e' rifiutata con exit 2
// invece di prendere silenziosamente l'ultima: un
// "--output-csv a.csv --output-csv b.csv" da script e' un bug del chiamante,
// non una preferenza (§2.2). Le esclusioni sono ripetibili per progetto, e un
// flag booleano ripetuto e' innocuo.
func Parse(args []string) (*Options, error) {
	if len(args) == 0 {
		return nil, usagef("nessun comando specificato")
	}

	o := &Options{Command: args[0]}
	if o.Command != "scan" && o.Command != "auto-rename" {
		return nil, usagef("comando sconosciuto %q: usare scan o auto-rename", o.Command)
	}

	// seen traccia le opzioni a occorrenza singola.
	seen := map[string]bool{}
	single := func(name, value string) (string, error) {
		if seen[name] {
			return "", usagef("l'opzione %s e' stata indicata piu' volte", name)
		}
		seen[name] = true
		return value, nil
	}

	rest := args[1:]
	for i := 0; i < len(rest); i++ {
		arg := rest[i]

		// Un "--" isolato termina le opzioni: cio' che segue e' un path anche
		// se inizia con un trattino.
		if arg == "--" {
			o.Paths = append(o.Paths, rest[i+1:]...)
			break
		}

		if !strings.HasPrefix(arg, "--") {
			o.Paths = append(o.Paths, arg)
			continue
		}

		name, inline, hasInline := strings.Cut(arg, "=")

		// value legge il valore dell'opzione, in forma "--opt=val" o "--opt val".
		value := func() (string, error) {
			if hasInline {
				return inline, nil
			}
			if i+1 >= len(rest) {
				return "", usagef("l'opzione %s richiede un valore", name)
			}
			i++
			return rest[i], nil
		}

		var err error
		switch name {
		case "--show-ok":
			o.ShowOK = true
		case "--show-excluded":
			o.ShowExcluded = true

		case "--exclude":
			var v string
			if v, err = value(); err == nil {
				o.Exclude = append(o.Exclude, v)
			}
		case "--exclude-regex":
			var v string
			if v, err = value(); err == nil {
				o.ExcludeRegex = append(o.ExcludeRegex, v)
			}

		case "--output-csv":
			var v string
			if v, err = value(); err == nil {
				o.OutputCSV, err = single(name, v)
			}
		case "--output-json":
			var v string
			if v, err = value(); err == nil {
				o.OutputJSON, err = single(name, v)
			}
		case "--emit-manifest":
			var v string
			if v, err = value(); err == nil {
				o.EmitManifest, err = single(name, v)
			}
		case "--journal":
			var v string
			if v, err = value(); err == nil {
				o.Journal, err = single(name, v)
			}

		default:
			return nil, usagef("opzione sconosciuta %s", name)
		}

		if err != nil {
			return nil, err
		}
	}

	if len(o.Paths) == 0 {
		return nil, usagef("nessun path indicato: serve almeno un argomento")
	}
	if o.Journal != "" && o.Command != "auto-rename" {
		return nil, usagef("--journal si applica solo ad auto-rename: scan non scrive mai")
	}
	if err := checkPaths(o.Paths); err != nil {
		return nil, err
	}
	return o, nil
}

// checkPaths rifiuta argomenti ripetuti o annidati.
//
// Vanno rilevati prima del walk e rifiutati con exit 2 invece di produrre righe
// duplicate: "a" e "a/b" descriverebbero due volte lo stesso sottoalbero, con
// due root diverse e conteggi di profondita' incoerenti (§2.1).
func checkPaths(paths []string) error {
	cleaned := make([]string, len(paths))
	for i, p := range paths {
		abs, err := filepath.Abs(p)
		if err != nil {
			return usagef("path non utilizzabile %q: %v", p, err)
		}
		cleaned[i] = filepath.Clean(abs)
	}

	for i := range cleaned {
		for j := range cleaned {
			if i == j {
				continue
			}
			if cleaned[i] == cleaned[j] && i < j {
				return usagef("il path %q e' indicato piu' volte", paths[i])
			}
			if isSubpath(cleaned[i], cleaned[j]) {
				return usagef("il path %q e' contenuto in %q: gli argomenti non possono annidarsi",
					paths[j], paths[i])
			}
		}
	}
	return nil
}

// isSubpath riporta se child sta sotto parent.
func isSubpath(parent, child string) bool {
	if parent == child {
		return false
	}
	rel, err := filepath.Rel(parent, child)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}
