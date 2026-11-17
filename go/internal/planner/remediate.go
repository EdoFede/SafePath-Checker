package planner

import (
	"strings"

	"github.com/EdoFede/safepath-checker/go/internal/rules"
)

// Remediate calcola il nome conforme corrispondente a name, applicando nella
// stessa sequenza le correzioni previste dalla tabella di rewrite di
// File naming Tech-rules §9.
//
// Restituisce anche i caratteri fuori profilo privi di sostituzione nella
// mappa: se l'elenco non e' vuoto il nome restituito non e' utilizzabile e
// l'entry va marcata manual (scelta dell'utente, non del documento).
//
// Case, spazi singoli e punti interni sono preservati: solo l'elemento in
// violazione viene modificato.
func Remediate(name string, kind rules.Kind) (string, []rune) {
	// NFC prima di tutto: corregge CHR-002 e rende prevedibili i confronti
	// successivi, perche' i caratteri precomposti sono quelli del Profilo B.
	s := rules.ToNFC(name)

	s, unmapped := applyCharMap(s)
	if len(unmapped) > 0 {
		return "", unmapped
	}

	s = collapseSpaces(s)
	s = collapseDots(s)
	s = fixReserved(s, kind)
	s = trimPositional(s)

	return s, nil
}

// applyCharMap sostituisce ogni carattere fuori Profilo B con la traslitterazione
// prevista da charMap, raccogliendo quelli che non ne hanno una.
//
// I marchi combinanti con una base valida sopravvivono alla normalizzazione NFC
// come carattere precomposto e non arrivano qui; un marchio standalone non e'
// mappabile e finisce fra i non mappati.
func applyCharMap(s string) (string, []rune) {
	var b strings.Builder
	b.Grow(len(s))

	var unmapped []rune
	seen := make(map[rune]bool)

	for _, r := range s {
		if rules.IsAllowed(r) && !rules.IsCombiningMark(r) {
			b.WriteRune(r)
			continue
		}
		if repl, ok := Replacement(r); ok {
			b.WriteString(repl)
			continue
		}
		if !seen[r] {
			seen[r] = true
			unmapped = append(unmapped, r)
		}
	}
	return b.String(), unmapped
}

// collapseSpaces riduce ogni sequenza di spazi a uno solo (POS-007).
func collapseSpaces(s string) string {
	for strings.Contains(s, "  ") {
		s = strings.ReplaceAll(s, "  ", " ")
	}
	return s
}

// collapseDots riduce ogni sequenza di punti a uno solo (POS-008).
//
// E' il caso di "Elenco soci S.p.A..pdf" -> "Elenco soci S.p.A.pdf" della
// tabella §9: l'abbreviazione che finisce con un punto, seguita dal punto
// dell'estensione.
func collapseDots(s string) string {
	for strings.Contains(s, "..") {
		s = strings.ReplaceAll(s, "..", ".")
	}
	return s
}

// trimPositional rimuove i caratteri illegali in testa e in coda: spazi, punti,
// virgole, trattini e tilde (POS-001..POS-006).
//
// Il ciclo e' necessario perche' una correzione ne puo' scoprire un'altra:
// " .-nome" richiede piu' passate.
func trimPositional(s string) string {
	for {
		before := s

		s = strings.Trim(s, " ")
		s = strings.TrimLeft(s, ".-~")
		s = strings.TrimRight(s, ".,")

		// Lo spazio in coda al basename e' POS-003 quanto quello finale:
		// "Riepilogo trimestrale .md" -> "Riepilogo trimestrale.md" (§9).
		if base, ext := rules.SplitExtension(s); ext != "" {
			if trimmed := strings.TrimRight(base, " "); trimmed != base {
				s = trimmed + ext
			}
		}

		if s == before {
			return s
		}
	}
}

// fixReserved rende non riservato un nome che collide con un device name
// Windows, un basename o un'estensione riservata (§4).
//
// La strategia segue l'esempio di §9 ("CON.docx" -> "Contratto CON.docx"): si
// antepone un prefisso descrittivo invece di alterare il nome esistente, che
// resta cosi' riconoscibile.
func fixReserved(s string, kind rules.Kind) string {
	// Basename riservati di sistema: non hanno un contenuto da preservare,
	// ma il rename deve comunque produrre un nome valido.
	if rules.IsReservedBasename(s) {
		return "file " + strings.TrimLeft(s, ".")
	}

	if rules.IsWindowsDevice(s) {
		prefix := "Documento "
		if kind == rules.KindDir {
			prefix = "Cartella "
		}
		return prefix + s
	}

	// Estensione riservata: il punto va neutralizzato, altrimenti il file
	// resta un temporaneo agli occhi dei client di sync.
	if base, ext := rules.SplitExtension(s); ext != "" && rules.IsReservedExtension(ext) {
		return base + " " + strings.TrimPrefix(ext, ".")
	}
	return s
}

// Nessuna correzione accorcia il nome. Un nome che resta oltre il limite di
// lunghezza viene rifiutato da resolveFree e l'entry diventa manual: troncare
// il nome di un documento e' un giudizio che il tool non e' autorizzato a dare
// al posto dell'utente (§8.3).
