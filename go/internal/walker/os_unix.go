//go:build !windows

package walker

import (
	"fmt"
	"os"
	"syscall"
)

// deviceID restituisce l'identificatore del filesystem che contiene path, usato
// per non attraversare i confini di mount (§7.3).
func deviceID(path string) (uint64, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return 0, err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, fmt.Errorf("informazioni di stat non disponibili per %q", path)
	}
	return uint64(st.Dev), nil
}

// isReparsePoint e' sempre falso su Unix: i reparse point sono un concetto
// Windows. I symlink sono gia' gestiti a parte.
func isReparsePoint(os.FileInfo) bool { return false }
