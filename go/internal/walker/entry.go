// Package walker attraversa il filesystem e produce le entry da validare.
//
// Tutta la divergenza fra sistemi operativi e' confinata qui: rules e planner
// non accedono al filesystem (Development guidelines §1).
package walker

import (
	"strings"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// Status e' lo stato di un'entry nel report (§3.1).
type Status string

const (
	StatusOK        Status = "ok"
	StatusViolation Status = "violation"
	StatusSkipped   Status = "skipped"
	StatusExcluded  Status = "excluded"
)

// Entry e' una singola entry incontrata durante la scansione.
//
// La serializzazione JSONL di []Entry e' il manifest opzionale (§1).
type Entry struct {
	Root    string     `json:"root"` // argomento di riga di comando, verbatim
	RelPath string     `json:"path"` // path relativo alla root, NFC, separatori "/"
	Kind    rules.Kind `json:"-"`    // serializzato attraverso Type
	Type    string     `json:"type"` // "file" | "dir"
	Status  Status     `json:"status"`
	Codes   []string   `json:"codes,omitempty"`

	// NFCNormalized registra se il nome su disco era gia' in NFC. Convertire
	// silenziosamente nasconderebbe le violazioni CHR-002, che sono gli
	// artefatti macOS/HFS+ che l'audit deve rilevare (§6.3).
	NFCNormalized bool `json:"nfc_normalized"`

	// ValidUTF8 e' false per i nomi Linux non decodificabili. PathB64 porta i
	// byte grezzi, perche' quei nomi non sono rappresentabili in JSON (§7.1).
	ValidUTF8 bool   `json:"valid_utf8"`
	PathB64   string `json:"path_b64,omitempty"`

	// SkipReason e' valorizzato per Status == StatusSkipped: symlink, entry
	// cross-device, directory illeggibile (§7.3).
	SkipReason string `json:"skip_reason,omitempty"`

	// ExcludedBy e' il primo pattern che ha escluso l'entry, e l'opzione da cui
	// proviene (§3.4).
	ExcludedBy   string      `json:"excluded_by,omitempty"`
	ExcludedKind PatternKind `json:"-"`

	// Size e ModTime finiscono solo nel manifest: differiscono fra host e sono
	// esclusi dal diff dei report (§13).
	Size    int64  `json:"size"`
	ModTime string `json:"mtime"`

	// abs e' il path assoluto su disco, per le operazioni di rename. Non e'
	// serializzato: e' specifico dell'host.
	abs string
}

// AbsPath restituisce il path assoluto dell'entry sul filesystem locale.
func (e Entry) AbsPath() string { return e.abs }

// SetAbsPath aggiorna il path assoluto dell'entry.
//
// Serve ad auto-rename: dopo aver rinominato una directory, il walker deve
// scendere nel nome nuovo, non in quello vecchio che non esiste piu' (§9.1).
func (e *Entry) SetAbsPath(abs string) { e.abs = abs }

// Name restituisce il componente finale del path relativo.
func (e Entry) Name() string {
	if i := strings.LastIndex(e.RelPath, "/"); i >= 0 {
		return e.RelPath[i+1:]
	}
	return e.RelPath
}

// bookkeepingPrefixes e bookkeepingSuffixes elencano i file di servizio di
// client e server, saltati incondizionatamente e indipendentemente da
// --exclude (§7.3).
//
// Uno skip di bookkeeping non e' un'esclusione: non viene mai riportato,
// nemmeno con --show-excluded (§2.3).
var (
	bookkeepingExact = map[string]bool{
		".nextcloud":     true,
		"files_versions": true,
		"files_trashbin": true,
	}
	bookkeepingPrefixes = []string{
		".sync_", ".owncloudsync.log", ".~lock.", "~$",
	}
	bookkeepingSuffixes = []string{
		".part", ".filepart",
	}
)

// tempPrefix e' il marcatore dei rinomini temporanei a due passi (§8.1).
// Il walk deve saltarli: un'esecuzione interrotta inquinerebbe il report
// successivo con i propri detriti.
const tempPrefix = ".safepath-"

// IsBookkeeping riporta se il nome e' un file di servizio da saltare
// incondizionatamente, temporanei di safepath inclusi.
func IsBookkeeping(name string) bool {
	lower := strings.ToLower(name)

	if bookkeepingExact[lower] {
		return true
	}
	if strings.Contains(name, tempPrefix) {
		return true
	}
	for _, p := range bookkeepingPrefixes {
		if strings.HasPrefix(lower, p) {
			return true
		}
	}
	for _, s := range bookkeepingSuffixes {
		if strings.HasSuffix(lower, s) {
			return true
		}
	}
	// .sync_*.db e' coperto dal prefisso .sync_; la variante con suffisso
	// numerico dei log di owncloud dal prefisso corrispondente.
	return false
}
