package planner

// Mappa di traslitterazione per la remediation dei caratteri fuori Profilo B.
//
// QUESTO FILE E' PENSATO PER ESSERE EDITATO. Aggiungere una riga qui e'
// sufficiente per rendere automaticamente correggibile un carattere che oggi
// produce action = manual: non c'e' altra logica da toccare.
//
// Criteri:
//   - la sostituzione deve essere composta solo da caratteri del Profilo B,
//     verificato dal test TestCharMapProducesValidChars;
//   - stringa vuota significa "rimuovi il carattere";
//   - le sostituzioni conservano il senso del nome, non lo abbreviano: la
//     tabella di rewrite di File naming Tech-rules §9 e' la fonte degli esempi.
//
// I caratteri fuori profilo NON presenti in questa mappa non vengono indovinati:
// l'entry diventa action = manual e il carattere compare nel riepilogo di fine
// esecuzione, che e' il posto da cui partire per estendere la mappa.
var charMap = map[rune]string{
	// --- Illegali su Windows / SMB (§2.3) ---
	'<':  "",
	'>':  "",
	':':  "h", // "12:30" -> "12h30", esempio di §9
	'"':  "",
	'/':  "-", // "12/2024" -> "12-2024", esempio di §9
	'\\': "-",
	'|':  "-",
	'?':  "",
	'*':  "",

	// --- URL / WebDAV unsafe (§2.3) ---
	'#': "n", // "#12" -> "n12", uso corrente come abbreviazione di "numero"
	'%': " pct",
	'+': " e ", // usato come congiunzione nei nomi di cartella reali
	'&': "e",   // "Rossi & C." -> "Rossi e C.", esempio di §9

	// --- Shell unsafe (§2.3) ---
	'$':  "",
	'`':  "",
	'\'': "", // "L'ISOLANTE" -> "LISOLANTE"
	'!':  "", // "[DEF]!" -> "DEF", esempio di §9
	';':  ",",
	'^':  "",
	'~':  "",
	'[':  "(",
	']':  ")",
	'{':  "(",
	'}':  ")",

	// --- Fuori profilo: punteggiatura tipografica (§2.3) ---
	'°': "",  // "n° 12" -> "n 12", esempio di §9
	'–': "-", // en dash
	'—': "-", // em dash
	'’': "",  // apostrofo tipografico
	'‘': "",
	'“': "",
	'”': "",
	'«': "",
	'»': "",
	'…': "",

	// --- Fuori profilo: simboli ricorrenti nei documenti amministrativi ---
	'€': " EUR",
	'£': " GBP",
	'@': " at ",
	'=': "-",
	'§': "par",
	'©': "(c)",
	'®': "(r)",
	'™': "(tm)",
	'µ': "u",
	'·': "-",
	'•': "-",

	// --- Controlli comuni (§2.3): rimossi, mai sostituiti con spazio ---
	'\t': " ",
	'\n': "",
	'\r': "",
}

// Replacement restituisce la sostituzione prevista per un carattere fuori
// profilo, e ok=false se il carattere non e' mappato.
//
// Un carattere non mappato non viene indovinato: rende l'entry action = manual
// (Development guidelines §3.2) e viene raccolto nel riepilogo di fine
// esecuzione.
func Replacement(r rune) (string, bool) {
	s, ok := charMap[r]
	return s, ok
}
