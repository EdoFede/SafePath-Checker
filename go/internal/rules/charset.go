package rules

import (
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// IsAlnum riporta se r e' un carattere alfanumerico del Profilo B: ASCII
// alfanumerico oppure una lettera Latin-1 Supplement / Latin Extended-A (§2.1).
func IsAlnum(r rune) bool {
	switch {
	case r >= 'A' && r <= 'Z', r >= 'a' && r <= 'z', r >= '0' && r <= '9':
		return true
	case r >= latin1SupLow && r <= latin1SupHigh:
		return true
	case r >= latin1SupLow2 && r <= latin1SupHi2:
		return true
	case r >= latinExtLow && r <= latinExtHigh:
		return true
	}
	return false
}

// IsAllowed riporta se r e' ammesso dal Profilo B in una qualsiasi posizione:
// alfanumerico oppure uno dei segni di punteggiatura consentiti (§2.1).
//
// Le regole posizionali (§3) sono verificate separatamente: un carattere puo'
// essere ammesso qui e comunque illegale nella posizione in cui compare.
func IsAllowed(r rune) bool {
	return IsAlnum(r) || strings.ContainsRune(punctuation, r)
}

// IsCombiningMark riporta se r appartiene alla categoria Unicode Mn, vietata
// dal Profilo B (§2.3).
//
// La categoria e' l'unico controllo di rules che dipende dalla tabella Unicode
// e non solo dalla normalizzazione, ed e' quindi la superficie di rischio
// descritta in Development guidelines §6.1.
func IsCombiningMark(r rune) bool {
	return unicode.Is(unicode.Mn, r)
}

// SplitExtension separa un componente file in basename ed estensione secondo la
// regola deterministica di §3.1: l'ultimo segmento separato da punto e'
// un'estensione solo se e' composto da 1..10 caratteri alfanumerici ASCII.
//
// L'estensione restituita include il punto. Se il componente non ha estensione
// valida, ext e' vuota e base e' il componente intero.
//
//	"Rossi e C. S.p.A.pdf"  -> "Rossi e C. S.p.A", ".pdf"
//	"archivio.tar.gz"       -> "archivio.tar",     ".gz"
//	"Verbale rev. 2"        -> "Verbale rev. 2",   ""       (segmento con spazio)
//	"Elenco soci S.p.A."    -> "Elenco soci S.p.A.", ""     (segmento vuoto)
func SplitExtension(name string) (base, ext string) {
	i := strings.LastIndex(name, ".")
	if i < 0 {
		return name, ""
	}
	seg := name[i+1:]
	if !isExtensionSegment(seg) {
		return name, ""
	}
	return name[:i], name[i:]
}

// isExtensionSegment verifica il predicato ^[A-Za-z0-9]{1,10}$ di §3.1.
func isExtensionSegment(seg string) bool {
	if len(seg) == 0 || len(seg) > 10 {
		return false
	}
	// Solo ASCII alfanumerico: un byte per carattere, nessun rune decoding.
	for i := 0; i < len(seg); i++ {
		c := seg[i]
		if (c < 'A' || c > 'Z') && (c < 'a' || c > 'z') && (c < '0' || c > '9') {
			return false
		}
	}
	return true
}

// DeviceSegment restituisce il segmento che precede il primo punto del
// componente, che e' l'ambito di confronto dei nomi di device Windows (§4).
//
//	"CON.rev 2.docx"          -> "CON"     (riservato)
//	"Documento CON allegati.pdf" -> "Documento CON allegati" (non riservato)
func DeviceSegment(name string) string {
	if i := strings.Index(name, "."); i >= 0 {
		return name[:i]
	}
	return name
}

// IsWindowsDevice riporta se il segmento che precede il primo punto e' un nome
// di device riservato da Win32 (§4). Il confronto e' case-insensitive.
func IsWindowsDevice(name string) bool {
	return windowsDeviceNames[strings.ToLower(DeviceSegment(name))]
}

// IsReservedBasename riporta se il componente intero e' un basename riservato
// di sistema (§4). Il confronto e' case-insensitive.
func IsReservedBasename(name string) bool {
	return reservedBasenames[strings.ToLower(name)]
}

// IsReservedExtension riporta se ext, punto incluso, e' un'estensione riservata
// (§4). Il confronto e' case-insensitive.
func IsReservedExtension(ext string) bool {
	return reservedExtensions[strings.ToLower(ext)]
}

// IsNFC riporta se s e' gia' in forma normale NFC.
//
// Il controllo e' distinto dalla conversione: convertire silenziosamente
// nasconderebbe le violazioni CHR-002, che sono esattamente gli artefatti
// HFS+/macOS che l'audit deve rilevare (Development guidelines §6.3).
func IsNFC(s string) bool {
	return norm.NFC.IsNormalString(s)
}

// ToNFC restituisce la forma normale NFC di s. Usata sui path scritti nei
// report e nel manifest, mai per alterare cio' che viene validato.
func ToNFC(s string) string {
	return norm.NFC.String(s)
}

// ToNFD restituisce la forma normale NFD di s, usata per i conteggi di
// lunghezza in caratteri e byte, che vanno fatti sul caso peggiore (§1).
func ToNFD(s string) string {
	return norm.NFD.String(s)
}
