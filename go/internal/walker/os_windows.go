//go:build windows

package walker

import (
	"os"
	"path/filepath"
	"syscall"

	"golang.org/x/sys/windows"

	"github.com/EdoFede/safepath-checker/go/internal/winpath"
)

// deviceID restituisce il numero di serie del volume che contiene path, che su
// Windows e' l'equivalente del device ID POSIX (§7.3).
func deviceID(path string) (uint64, error) {
	abs, err := winpath.Abs(path)
	if err != nil {
		return 0, err
	}

	// GetVolumeInformation richiede la radice del volume con separatore finale.
	root := filepath.VolumeName(abs) + `\`
	rootPtr, err := windows.UTF16PtrFromString(root)
	if err != nil {
		return 0, err
	}

	var serial uint32
	err = windows.GetVolumeInformation(rootPtr, nil, 0, &serial, nil, nil, nil, 0)
	if err != nil {
		return 0, err
	}
	return uint64(serial), nil
}

// isReparsePoint riporta se l'entry e' un reparse point (junction, mount point,
// symlink NTFS). Non va attraversato: romperebbe il conteggio della profondita'
// e puo' produrre cicli (§7.3).
func isReparsePoint(info os.FileInfo) bool {
	d, ok := info.Sys().(*syscall.Win32FileAttributeData)
	if !ok {
		return false
	}
	return d.FileAttributes&syscall.FILE_ATTRIBUTE_REPARSE_POINT != 0
}
