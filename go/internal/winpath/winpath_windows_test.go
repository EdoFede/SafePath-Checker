//go:build windows

package winpath

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLongForms(t *testing.T) {
	cases := map[string]string{
		`D:\a\CON.CA. x`:      `\\?\D:\a\CON.CA. x`,
		`D:\a\nome finale. `:  `\\?\D:\a\nome finale. `,
		`D:\a\.\b\..\c`:       `\\?\D:\a\c`,
		`\\srv\share\a\b`:     `\\?\UNC\srv\share\a\b`,
		`\\?\D:\gia\prefisso`: `\\?\D:\gia\prefisso`,
	}
	for in, want := range cases {
		if got := Long(in); got != want {
			t.Errorf("Long(%q) = %q, want %q", in, got, want)
		}
	}
}

// Un nome che Win32 risolverebbe sul device console deve restare accessibile.
func TestDeviceNameRoundTrip(t *testing.T) {
	dir := t.TempDir()
	name := filepath.Join(dir, "CON.CA. prova")

	if err := os.WriteFile(Long(name), []byte("x"), 0o644); err != nil {
		t.Fatalf("creazione: %v", err)
	}
	if _, err := os.Lstat(Long(name)); err != nil {
		t.Fatalf("lstat: %v", err)
	}
	if err := os.Rename(Long(name), Long(filepath.Join(dir, "Contratto CON.CA prova"))); err != nil {
		t.Fatalf("rename: %v", err)
	}
}
