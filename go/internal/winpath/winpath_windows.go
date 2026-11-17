//go:build windows

package winpath

import (
	"path/filepath"
	"strings"
)

// Abs restituisce la forma assoluta di path senza passare da
// GetFullPathName quando path e' gia' assoluto: quella chiamata applica la
// normalizzazione Win32 e trasformerebbe "D:\x\CON.CA. y" in "\\.\CON".
func Abs(path string) (string, error) {
	if filepath.IsAbs(path) {
		return filepath.Clean(path), nil
	}
	return filepath.Abs(path)
}

// Long antepone \\?\ (o \\?\UNC\ per i path di rete).
//
// La forma \\?\ richiede backslash, un path assoluto e nessun componente "."
// o "..": Abs e Clean li garantiscono prima del prefisso.
func Long(path string) string {
	if strings.HasPrefix(path, `\\?\`) {
		return path
	}
	abs, err := Abs(path)
	if err != nil {
		return path
	}
	if strings.HasPrefix(abs, `\\`) {
		return `\\?\UNC\` + strings.TrimPrefix(abs, `\\`)
	}
	return `\\?\` + abs
}
