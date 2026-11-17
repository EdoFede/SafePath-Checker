package walker

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
	"github.com/EdoFede/safepath-checker/go/internal/winpath"
)

// Options configura una scansione.
type Options struct {
	Matcher *Matcher // pattern di esclusione utente; nil = nessuna esclusione

	// DirHook, se valorizzato, e' invocato su ogni directory dopo che il suo
	// listing e' stato prodotto e prima di scendere nelle sottodirectory.
	//
	// E' il punto di innesto di auto-rename, che rinomina mentre discende: le
	// entry restituite sostituiscono quelle passate, cosi' che i figli siano
	// scoperti e riportati sotto il nome definitivo del padre (§9.1).
	DirHook DirHook
}

// DirHook riceve il listing di una directory e puo' modificarlo prima che il
// walk prosegua. dirAbs e' il path assoluto della directory contenitrice.
type DirHook func(dirAbs string, entries []Entry) ([]Entry, error)

// Walk attraversa root e restituisce le entry incontrate, ordinate per byte
// order del path NFC (§5).
//
// rootArg e' l'argomento verbatim di riga di comando, riportato nella colonna
// root; root e' il path risolto su disco. La scan root non e' validata come
// componente: solo il suo contenuto (§2.1).
func Walk(rootArg, root string, opts Options) ([]Entry, error) {
	info, err := os.Lstat(winpath.Long(root))
	if err != nil {
		return nil, fmt.Errorf("impossibile leggere la scan root %q: %w", rootArg, err)
	}

	// Un argomento che punta a un singolo file viene validato da solo (§2.1).
	if !info.IsDir() {
		e := newEntry(rootArg, info.Name(), root, info)
		return []Entry{e}, nil
	}

	rootDev, err := deviceID(root)
	if err != nil {
		return nil, fmt.Errorf("impossibile identificare il device di %q: %w", rootArg, err)
	}

	w := &walk{
		rootArg: rootArg,
		root:    root,
		dev:     rootDev,
		opts:    opts,
	}
	if err := w.descend(root, ""); err != nil {
		return nil, err
	}

	sort.Slice(w.entries, func(i, j int) bool {
		return w.entries[i].RelPath < w.entries[j].RelPath
	})
	return w.entries, nil
}

// walk porta lo stato di una singola scansione.
type walk struct {
	rootArg string
	root    string
	dev     uint64
	opts    Options
	entries []Entry
}

// descend elabora una directory per volta, completandola prima di scendere,
// come richiede il ciclo per-directory di §9.1.
func (w *walk) descend(dirAbs, dirRel string) error {
	names, err := readDirNames(dirAbs)
	if err != nil {
		// Una directory illeggibile e' una riga skipped e il walk prosegue: un
		// errore di permessi non interrompe l'esecuzione (§7.3).
		w.entries = append(w.entries, Entry{
			Root:       w.rootArg,
			RelPath:    normalizeRel(dirRel),
			Kind:       rules.KindDir,
			Type:       rules.KindDir.String(),
			Status:     StatusSkipped,
			SkipReason: fmt.Sprintf("directory illeggibile: %v", err),
			ValidUTF8:  utf8.ValidString(dirRel),
			abs:        dirAbs,
		})
		return nil
	}

	// L'ordine di readdir differisce fra ext4, NTFS e APFS: ordinare ogni
	// listing e' cio' che rende deterministico anche l'ordine dei rename, non
	// solo quello del report (§7.3).
	sort.Slice(names, func(i, j int) bool {
		return rules.ToNFC(names[i]) < rules.ToNFC(names[j])
	})

	listing := make([]Entry, 0, len(names))
	for _, name := range names {
		if IsBookkeeping(name) {
			continue // mai riportato, nemmeno con --show-excluded (§2.3)
		}

		abs := filepath.Join(dirAbs, name)
		info, err := os.Lstat(winpath.Long(abs))
		if err != nil {
			listing = append(listing, w.skipped(name, dirRel, abs, rules.KindFile,
				fmt.Sprintf("impossibile leggere l'entry: %v", err)))
			continue
		}

		if e, skip := w.checkTraversable(name, dirRel, abs, info); skip {
			listing = append(listing, e)
			continue
		}

		listing = append(listing, newEntry(w.rootArg, name, abs, info))
	}

	// Il path relativo va completato prima dell'hook: auto-rename ragiona su
	// path relativi alla root, non su nomi isolati.
	for i := range listing {
		listing[i].RelPath = normalizeRel(joinRel(dirRel, listing[i].RelPath))
	}

	listing = w.applyExclusions(listing)

	if w.opts.DirHook != nil {
		listing, err = w.opts.DirHook(dirAbs, listing)
		if err != nil {
			return err
		}
	}

	w.entries = append(w.entries, listing...)

	// La discesa avviene dopo l'hook, sotto i nomi definitivi: nessun path
	// registrato in precedenza diventa obsoleto (§9.1).
	for _, e := range listing {
		if e.Kind != rules.KindDir || e.Status == StatusSkipped || e.Status == StatusExcluded {
			continue
		}
		if err := w.descend(e.abs, e.RelPath); err != nil {
			return err
		}
	}
	return nil
}

// checkTraversable applica le regole di traversal di §7.3: symlink e reparse
// point non vengono seguiti, i confini di filesystem non vengono attraversati.
func (w *walk) checkTraversable(name, dirRel, abs string, info os.FileInfo) (Entry, bool) {
	kind := rules.KindFile
	if info.IsDir() {
		kind = rules.KindDir
	}

	// Seguire i symlink romperebbe il conteggio della profondita' e puo'
	// produrre cicli.
	if info.Mode()&os.ModeSymlink != 0 {
		return w.skipped(name, dirRel, abs, kind, "symlink non attraversato"), true
	}
	if isReparsePoint(info) {
		return w.skipped(name, dirRel, abs, kind, "reparse point non attraversato"), true
	}

	if info.IsDir() {
		dev, err := deviceID(abs)
		if err != nil {
			return w.skipped(name, dirRel, abs, kind,
				fmt.Sprintf("impossibile identificare il device: %v", err)), true
		}
		if dev != w.dev {
			return w.skipped(name, dirRel, abs, kind, "confine di filesystem non attraversato"), true
		}
	}
	return Entry{}, false
}

// skipped costruisce una riga skipped. Il RelPath e' ancora il solo nome: viene
// completato dal chiamante.
func (w *walk) skipped(name, dirRel, abs string, kind rules.Kind, reason string) Entry {
	return Entry{
		Root:       w.rootArg,
		RelPath:    name,
		Kind:       kind,
		Type:       kind.String(),
		Status:     StatusSkipped,
		SkipReason: reason,
		ValidUTF8:  utf8.ValidString(name),
		abs:        abs,
	}
}

// applyExclusions marca le entry che corrispondono ai pattern utente.
//
// Una directory esclusa esclude l'intero sottoalbero, che non viene proprio
// percorso: e' cio' che rende --exclude 'node_modules' economico e non solo
// silenzioso (§2.3).
func (w *walk) applyExclusions(listing []Entry) []Entry {
	if w.opts.Matcher == nil {
		return listing
	}

	for i := range listing {
		if listing[i].Status == StatusSkipped {
			continue
		}
		if p, ok := w.opts.Matcher.Match(listing[i].Name(), listing[i].RelPath); ok {
			listing[i].Status = StatusExcluded
			listing[i].ExcludedBy = p.Raw
			listing[i].ExcludedKind = p.Kind
		}
	}
	return listing
}

// newEntry costruisce un'entry a partire dal nome su disco.
func newEntry(rootArg, name, abs string, info os.FileInfo) Entry {
	kind := rules.KindFile
	if info.IsDir() {
		kind = rules.KindDir
	}

	valid := utf8.ValidString(name)
	e := Entry{
		Root:      rootArg,
		RelPath:   name,
		Kind:      kind,
		Type:      kind.String(),
		ValidUTF8: valid,
		// Registrato prima di qualsiasi conversione: e' l'informazione che
		// CHR-002 rende visibile (§6.3).
		NFCNormalized: rules.IsNFC(name),
		Size:          info.Size(),
		ModTime:       info.ModTime().UTC().Format(time.RFC3339),
		abs:           abs,
	}
	if !valid {
		e.PathB64 = base64.StdEncoding.EncodeToString([]byte(name))
	}
	return e
}

// readDirNames restituisce i nomi contenuti in una directory, senza ordinamento
// (l'ordinamento e' responsabilita' del chiamante).
func readDirNames(dir string) ([]string, error) {
	f, err := os.Open(winpath.Long(dir))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return f.Readdirnames(-1)
}

// joinRel concatena il path relativo della directory con il nome di un'entry.
func joinRel(dirRel, name string) string {
	if dirRel == "" {
		return name
	}
	return dirRel + "/" + name
}

// normalizeRel porta un path relativo nella forma dei report: NFC, separatori
// "/", nessun "./" iniziale (§5).
func normalizeRel(p string) string {
	p = strings.ReplaceAll(p, string(filepath.Separator), "/")
	p = strings.TrimPrefix(p, "./")
	return rules.ToNFC(p)
}
