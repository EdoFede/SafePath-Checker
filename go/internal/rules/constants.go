package rules

// Limiti di lunghezza e profondita' (File naming Tech-rules §1).
//
// Vale l'invariante DirPathMaxChars + 1 + FileNameMaxChars == RelPathMaxChars.
// Tutti i limiti si applicano simultaneamente: nessuno implica gli altri.
const (
	// RelPathMaxChars e' il limite applicato al path relativo alla scan root.
	// Deriva da 259 (Windows MAX_PATH) - 50 (prefisso riservato) - 25 (suffisso
	// di conflitto NextCloud), arrotondato a 180.
	RelPathMaxChars = 180

	// DirPathMaxChars limita la porzione di directory del path relativo,
	// separatore finale escluso.
	DirPathMaxChars = 115

	// FileNameMaxChars limita il componente finale di un file, estensione inclusa.
	FileNameMaxChars = 64

	// DirNameMaxChars limita il nome di un componente directory.
	DirNameMaxChars = 48

	// ComponentMaxBytes limita un componente in byte UTF-8 della forma NFD,
	// con margine rispetto a NAME_MAX (255) dei filesystem POSIX.
	ComponentMaxBytes = 200

	// MaxDepth e' il numero massimo di livelli di directory sotto la scan root.
	MaxDepth = 6
)

// Intervalli di caratteri ammessi dal Profilo B (§2.1): Latin-1 Supplement e
// Latin Extended-A, esclusi i due punti di divisione (U+00D7 e U+00F7, che sono
// i segni di moltiplicazione e divisione, non lettere).
const (
	latin1SupLow  = 0x00C0
	latin1SupHigh = 0x00D6
	latin1SupLow2 = 0x00D8
	latin1SupHi2  = 0x00F6
	latinExtLow   = 0x00F8
	latinExtHigh  = 0x017F
)

// punctuation elenca i caratteri non alfanumerici ammessi dal Profilo B (§2.1).
const punctuation = " -_.(),"

// windowsDeviceNames sono i nomi di device riservati da Win32 (§4). Il
// confronto e' case-insensitive e avviene sul segmento che precede il primo
// punto, con o senza qualsiasi cosa segua.
var windowsDeviceNames = map[string]bool{
	"con": true, "prn": true, "aux": true, "nul": true,
	"clock$": true, "conin$": true, "conout$": true,
	"com0": true, "com1": true, "com2": true, "com3": true, "com4": true,
	"com5": true, "com6": true, "com7": true, "com8": true, "com9": true,
	"lpt0": true, "lpt1": true, "lpt2": true, "lpt3": true, "lpt4": true,
	"lpt5": true, "lpt6": true, "lpt7": true, "lpt8": true, "lpt9": true,
}

// reservedBasenames sono confrontati con il componente intero, case-insensitive (§4).
// "Icon\r" e' l'artefatto Finder di macOS, con un CR letterale in coda.
var reservedBasenames = map[string]bool{
	".ds_store": true, "icon\r": true, ".appledouble": true,
	".appledb": true, ".appledesktop": true, ".temporaryitems": true,
	".spotlight-v100": true, ".fseventsd": true, ".trashes": true,
	".htaccess": true, ".ocdata": true, ".sync-exclude.lst": true,
	".snapshot": true, "desktop.ini": true,
}

// reservedExtensions sono confrontate con l'estensione come definita in §3.1,
// case-insensitive, punto incluso.
var reservedExtensions = map[string]bool{
	".part": true, ".filepart": true, ".tmp": true,
}
