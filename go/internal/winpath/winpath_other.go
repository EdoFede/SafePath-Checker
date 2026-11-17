//go:build !windows

package winpath

import "path/filepath"

// Abs equivale a filepath.Abs: fuori da Windows non c'e' normalizzazione da
// evitare.
func Abs(path string) (string, error) { return filepath.Abs(path) }

// Long restituisce path invariato: il prefisso \\?\ e' specifico di Windows.
// Su macOS PATH_MAX e' 1024 byte e non e' aggirabile.
func Long(path string) string { return path }
