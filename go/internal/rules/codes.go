// Package rules implementa la validazione dei nomi secondo il Profilo B.
//
// Nessuna funzione di questo package accede al filesystem: riceve nomi e path
// gia' estratti dal walker e restituisce violazioni. Questo e' cio' che rende i
// risultati identici su ogni piattaforma (Development guidelines §1).
package rules

// RulesetVersion identifica la revisione delle regole implementate. Compare
// nell'header dei report ed e' confrontata dai test di parita' (§10).
const RulesetVersion = "1"

// Codici di violazione (File naming Tech-rules §7).
const (
	CodeCHR001 = "CHR-001" // carattere fuori Profilo B
	CodeCHR002 = "CHR-002" // nome non in forma NFC
	CodePOS001 = "POS-001" // punto iniziale
	CodePOS002 = "POS-002" // punto o virgola finale
	CodePOS003 = "POS-003" // spazio iniziale o finale
	CodePOS004 = "POS-004" // prefisso AppleDouble "._"
	CodePOS005 = "POS-005" // trattino iniziale
	CodePOS006 = "POS-006" // tilde iniziale
	CodePOS007 = "POS-007" // spazi consecutivi
	CodePOS008 = "POS-008" // punti consecutivi
	CodeRSV001 = "RSV-001" // nome di device Windows
	CodeRSV002 = "RSV-002" // basename riservato
	CodeRSV003 = "RSV-003" // estensione riservata
	CodeLEN001 = "LEN-001" // path relativo troppo lungo
	CodeLEN002 = "LEN-002" // porzione directory troppo lunga
	CodeLEN003 = "LEN-003" // nome file troppo lungo (caratteri)
	CodeLEN004 = "LEN-004" // nome directory troppo lungo (caratteri)
	CodeLEN005 = "LEN-005" // componente troppo lungo (byte, NFD)
	CodeLEN006 = "LEN-006" // profondita' eccessiva
	CodeUNQ001 = "UNQ-001" // collisione case-insensitive
	CodePTH001 = "PTH-001" // path vuoto
)

// descriptions associa a ogni codice la descrizione italiana usata nella
// colonna detail del report (§3.1).
var descriptions = map[string]string{
	CodeCHR001: "carattere non ammesso dal Profilo B",
	CodeCHR002: "nome non in forma normale NFC",
	CodePOS001: "il nome inizia con un punto",
	CodePOS002: "il nome termina con un punto o una virgola",
	CodePOS003: "il nome inizia o termina con uno spazio",
	CodePOS004: "il nome inizia con il prefisso AppleDouble \"._\"",
	CodePOS005: "il nome inizia con un trattino",
	CodePOS006: "il nome inizia con una tilde",
	CodePOS007: "il nome contiene spazi consecutivi",
	CodePOS008: "il nome contiene punti consecutivi",
	CodeRSV001: "nome riservato di device Windows",
	CodeRSV002: "basename riservato di sistema",
	CodeRSV003: "estensione riservata",
	CodeLEN001: "path relativo troppo lungo",
	CodeLEN002: "porzione di directory del path troppo lunga",
	CodeLEN003: "nome file troppo lungo",
	CodeLEN004: "nome directory troppo lungo",
	CodeLEN005: "componente troppo lungo in byte (UTF-8 di NFD)",
	CodeLEN006: "profondita' di annidamento eccessiva",
	CodeUNQ001: "collisione case-insensitive con un altro nome nella stessa directory",
	CodePTH001: "path vuoto",
}

// Describe restituisce la descrizione italiana di un codice di violazione.
// Per un codice sconosciuto restituisce il codice stesso, cosi' che un report
// resti leggibile anche se il codice non e' ancora mappato.
func Describe(code string) string {
	if d, ok := descriptions[code]; ok {
		return d
	}
	return code
}
