package rules

import "golang.org/x/text/cases"

// folder esegue il full case folding Unicode. E' stateless e sicuro per l'uso
// concorrente. cases.Fold() non accetta tag di lingua, quindi non introduce
// alcuna regola locale-specifica: il contratto di determinismo vieta il locale
// (Development guidelines §5).
var folder = cases.Fold()

// CollisionKey restituisce la chiave di confronto per l'unicita'
// case-insensitive: casefold(NFC(name)) (File naming Tech-rules §5).
//
// Il full case folding non e' equivalente al lowercasing e strings.ToLower non
// puo' essere usato qui: "ß" diventa "ss" e "ﬁ" diventa "fi" solo con il
// folding. Il Profilo B rifiuta questi caratteri come CHR-001, ma il controllo
// di collisione gira sul dataset pre-remediation, che contiene nomi legacy
// arbitrari (Development guidelines §6.2).
//
// Il confronto e' valido solo fra nomi della stessa directory.
func CollisionKey(name string) string {
	return folder.String(ToNFC(name))
}

// foldPattern applica lo stesso folding ai pattern di esclusione, per il
// matching case-insensitive richiesto da Development guidelines §2.3.
func foldPattern(s string) string {
	return folder.String(ToNFC(s))
}

// FoldPattern e' l'entry point pubblico di foldPattern, usato dal walker per
// normalizzare i pattern di esclusione prima del confronto.
func FoldPattern(s string) string { return foldPattern(s) }
