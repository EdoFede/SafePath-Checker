package rename

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/EdoFede/safepath-checker/go/internal/winpath"
)

// TempPrefix marca i nomi temporanei del doppio passaggio. Deve restare
// allineato a walker.tempPrefix, che li esclude dal walk: un'esecuzione
// interrotta inquinerebbe altrimenti il report successivo con i propri detriti
// (§8.1).
const TempPrefix = ".safepath-"

// TempName costruisce il nome temporaneo per una destinazione.
//
// E' deterministico, derivato da un hash del nome di destinazione: cosi'
// un'esecuzione andata in crash puo' essere ripresa e il residuo riconosciuto.
func TempName(targetName string) string {
	sum := sha256.Sum256([]byte(targetName))
	return targetName + TempPrefix + hex.EncodeToString(sum[:])[:12]
}

// Orphan e' un temporaneo rimasto da un'esecuzione interrotta.
type Orphan struct {
	Dir  string // directory che lo contiene
	Name string // nome del temporaneo
	// Target e' il nome di destinazione che il temporaneo stava per assumere,
	// ricavato dal nome stesso.
	Target string
}

// FindOrphans cerca i temporanei rimasti sotto root.
//
// auto-rename deve essere tollerante ai crash: all'avvio cerca i residui
// "*.safepath-*" e li completa o li annulla (§8.1, §9.4).
func FindOrphans(root string) ([]Orphan, error) {
	var orphans []Orphan

	err := filepath.WalkDir(winpath.Long(root), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			// Una directory illeggibile non deve interrompere il recupero:
			// gli altri residui vanno comunque trovati.
			return nil //nolint:nilerr
		}
		name := d.Name()
		if i := strings.Index(name, TempPrefix); i > 0 {
			orphans = append(orphans, Orphan{
				Dir:    filepath.Dir(path),
				Name:   name,
				Target: name[:i],
			})
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("ricerca dei temporanei sotto %q: %w", root, err)
	}

	// Ordine fissato: il recupero deve essere riproducibile quanto il walk.
	sort.Slice(orphans, func(i, j int) bool {
		if orphans[i].Dir != orphans[j].Dir {
			return orphans[i].Dir < orphans[j].Dir
		}
		return orphans[i].Name < orphans[j].Name
	})
	return orphans, nil
}

// RecoverOrphan completa un'operazione interrotta portando il temporaneo al
// nome di destinazione, se quel nome e' libero.
//
// Se la destinazione e' occupata il temporaneo viene lasciato dov'e' e l'errore
// riportato: rimuoverlo o sovrascrivere la destinazione sono decisioni che il
// tool non prende da solo.
func RecoverOrphan(o Orphan) error {
	tmpPath := winpath.Long(filepath.Join(o.Dir, o.Name))
	targetPath := winpath.Long(filepath.Join(o.Dir, o.Target))

	if _, err := os.Lstat(targetPath); err == nil {
		return fmt.Errorf("il temporaneo %q non puo' essere completato: %q esiste gia'",
			o.Name, o.Target)
	}

	if err := os.Rename(tmpPath, targetPath); err != nil {
		return fmt.Errorf("completamento del temporaneo %q: %w", o.Name, err)
	}
	return nil
}
