//go:build windows

package report

import (
	"os"

	"golang.org/x/sys/windows"
)

// enableVT attiva l'interpretazione delle sequenze ANSI sulla console. Prima di
// Windows 10 il flag non esiste e SetConsoleMode fallisce: in quel caso il
// colore va disattivato, altrimenti le sequenze compaiono come testo.
func enableVT(out *os.File) bool {
	h := windows.Handle(out.Fd())
	var mode uint32
	if err := windows.GetConsoleMode(h, &mode); err != nil {
		return false
	}
	if mode&windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING != 0 {
		return true
	}
	return windows.SetConsoleMode(h, mode|windows.ENABLE_VIRTUAL_TERMINAL_PROCESSING) == nil
}
