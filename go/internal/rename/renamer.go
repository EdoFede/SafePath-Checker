// Package rename esegue le operazioni di rinomina sul filesystem.
//
// L'interfaccia Renamer isola il trasporto: oggi esiste il solo backend
// filesystem, ma un backend WebDAV MOVE contro il server NextCloud puo' essere
// aggiunto senza toccare walker, rules o planner (Development guidelines §8.5).
//
// Il rename diretto sul filesystem del server scavalca il database NextCloud e
// i client vedono delete + create: e' accettabile per alberi non ancora
// condivisi, non per alberi con share, versioni o commenti da preservare.
package rename

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
	"github.com/EdoFede/safepath-checker/go/internal/winpath"
)

// Renamer esegue una rinomina all'interno di una directory.
type Renamer interface {
	// Rename rinomina oldName in newName dentro dirAbs. Entrambi i nomi sono
	// componenti singoli, non path.
	Rename(dirAbs, oldName, newName string) error

	// List restituisce i nomi presenti nella directory, letti in quel momento.
	// Il chiamante lo usa per la verifica per ri-lettura (§9.3) e per il
	// controllo di collisione contro il listing vivo (§8.2).
	List(dirAbs string) ([]string, error)
}

// FSRenamer e' il backend filesystem.
type FSRenamer struct{}

// List legge il contenuto della directory dal filesystem.
func (FSRenamer) List(dirAbs string) ([]string, error) {
	f, err := os.Open(winpath.Long(dirAbs))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return f.Readdirnames(-1)
}

// Rename esegue la rinomina, gestendo il caso case-only con il doppio passaggio
// obbligatorio (§8.1).
//
// Non usa mai una replace nuda: su un filesystem case-insensitive rinominare
// "A.txt" in "b.txt" quando "B.txt" esiste sovrascriverebbe silenziosamente.
// La verifica di disponibilita' spetta al chiamante, che la esegue contro il
// listing vivo immediatamente prima (§8.2).
func (r FSRenamer) Rename(dirAbs, oldName, newName string) error {
	oldPath := filepath.Join(dirAbs, oldName)
	newPath := filepath.Join(dirAbs, newName)

	// Una rinomina che cambia solo il case e' rifiutata, ignorata o accettata a
	// seconda del filesystem e della versione di OS: non ci si puo' mai
	// contare. Il doppio passaggio la rende affidabile ovunque.
	if isCaseOnlyChange(oldName, newName) {
		return r.renameViaTemp(dirAbs, oldName, newName)
	}

	return os.Rename(winpath.Long(oldPath), winpath.Long(newPath))
}

// isCaseOnlyChange riporta se i due nomi differiscono solo per il case, cioe'
// se hanno la stessa chiave di collisione ma non gli stessi byte.
func isCaseOnlyChange(oldName, newName string) bool {
	return oldName != newName &&
		rules.CollisionKey(oldName) == rules.CollisionKey(newName)
}

// renameViaTemp esegue la rinomina in due passi attraverso un nome temporaneo
// deterministico (§8.1).
//
//	Bilancio.xlsx -> Bilancio.xlsx.safepath-<hash> -> bilancio.xlsx
//
// Il temporaneo sta nella stessa directory (evita EXDEV), ha un prefisso
// riconoscibile perche' una passata di recupero possa completare o annullare
// un'operazione interrotta, ed e' derivato da un hash del path di destinazione
// cosi' che un'esecuzione andata in crash sia riprendibile.
func (r FSRenamer) renameViaTemp(dirAbs, oldName, newName string) error {
	tmpName := TempName(newName)
	tmpPath := winpath.Long(filepath.Join(dirAbs, tmpName))

	// Il temporaneo non deve gia' esistere: un residuo di un'esecuzione
	// precedente va riconosciuto, non sovrascritto.
	if _, err := os.Lstat(tmpPath); err == nil {
		return fmt.Errorf("il nome temporaneo %q esiste gia': recupero necessario", tmpName)
	}

	if err := os.Rename(winpath.Long(filepath.Join(dirAbs, oldName)), tmpPath); err != nil {
		return fmt.Errorf("primo passo della rinomina case-only: %w", err)
	}

	if err := os.Rename(tmpPath, winpath.Long(filepath.Join(dirAbs, newName))); err != nil {
		// Il ripristino riporta il nome originale, cosi' che un fallimento non
		// lasci l'albero con un temporaneo al posto del file.
		if restoreErr := os.Rename(tmpPath, winpath.Long(filepath.Join(dirAbs, oldName))); restoreErr != nil {
			return fmt.Errorf("secondo passo fallito (%w) e ripristino fallito (%v): "+
				"il file resta come %q", err, restoreErr, tmpName)
		}
		return fmt.Errorf("secondo passo della rinomina case-only: %w", err)
	}
	return nil
}
