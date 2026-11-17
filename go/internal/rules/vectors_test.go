package rules

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"testing"
)

// testVectors rispecchia shared/testvectors.json, che e' l'unica fonte dei
// vettori normativi: nessuna implementazione ne tiene una copia propria
// (Development guidelines §10).
type testVectors struct {
	RulesetVersion string `json:"ruleset_version"`

	PathVectors []struct {
		Path   string   `json:"path"`
		Kind   string   `json:"kind"`
		Codes  []string `json:"codes"`
		Source string   `json:"source"`
	} `json:"path_vectors"`

	ComponentVectors []struct {
		Name   string   `json:"name"`
		Kind   string   `json:"kind"`
		Codes  []string `json:"codes"`
		Source string   `json:"source"`
	} `json:"component_vectors"`

	CollisionVectors []struct {
		Names     []string `json:"names"`
		Colliding []string `json:"colliding"`
		Source    string   `json:"source"`
	} `json:"collision_vectors"`

	ExtensionVectors []struct {
		Name   string `json:"name"`
		Base   string `json:"base"`
		Ext    string `json:"ext"`
		Source string `json:"source"`
	} `json:"extension_vectors"`
}

// loadVectors legge shared/testvectors.json risalendo dalla directory del
// package. Il path e' relativo per non dipendere dalla posizione del checkout.
func loadVectors(t *testing.T) testVectors {
	t.Helper()

	path := filepath.Join("..", "..", "..", "shared", "testvectors.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("lettura di %s: %v", path, err)
	}

	var v testVectors
	if err := json.Unmarshal(data, &v); err != nil {
		t.Fatalf("parsing di %s: %v", path, err)
	}
	return v
}

// parseKind converte il campo kind dei vettori nel tipo interno.
func parseKind(t *testing.T, s string) Kind {
	t.Helper()
	switch s {
	case "dir":
		return KindDir
	case "file":
		return KindFile
	}
	t.Fatalf("kind sconosciuto nei vettori: %q", s)
	return KindFile
}

// normalizeCodes rende confrontabili nil e slice vuota, che nei vettori JSON
// sono entrambi rappresentati da [].
func normalizeCodes(c []string) []string {
	if c == nil {
		return []string{}
	}
	sort.Strings(c)
	return c
}

// TestRulesetVersionMatches verifica che la costante del codice e i vettori
// dichiarino la stessa revisione delle regole: se divergono, i vettori non
// stanno testando la versione che si crede (§10).
func TestRulesetVersionMatches(t *testing.T) {
	v := loadVectors(t)
	if v.RulesetVersion != RulesetVersion {
		t.Errorf("ruleset_version dei vettori = %q, costante = %q",
			v.RulesetVersion, RulesetVersion)
	}
}

func TestPathVectors(t *testing.T) {
	v := loadVectors(t)
	if len(v.PathVectors) == 0 {
		t.Fatal("nessun path vector caricato")
	}

	for _, vec := range v.PathVectors {
		t.Run(vec.Path, func(t *testing.T) {
			got := ValidatePath(Target{
				RelPath:   vec.Path,
				Kind:      parseKind(t, vec.Kind),
				ValidUTF8: true,
			})
			want := normalizeCodes(vec.Codes)
			if !reflect.DeepEqual(normalizeCodes(got), want) {
				t.Errorf("ValidatePath(%q) = %v, atteso %v\n  fonte: %s",
					vec.Path, got, want, vec.Source)
			}
		})
	}
}

func TestComponentVectors(t *testing.T) {
	v := loadVectors(t)

	for _, vec := range v.ComponentVectors {
		t.Run(vec.Name, func(t *testing.T) {
			got := ValidateComponent(vec.Name, parseKind(t, vec.Kind))
			want := normalizeCodes(vec.Codes)
			if !reflect.DeepEqual(normalizeCodes(got), want) {
				t.Errorf("ValidateComponent(%q) = %v, atteso %v\n  fonte: %s",
					vec.Name, got, want, vec.Source)
			}
		})
	}
}

func TestCollisionVectors(t *testing.T) {
	v := loadVectors(t)

	for _, vec := range v.CollisionVectors {
		t.Run(vec.Names[0], func(t *testing.T) {
			colliding := CheckCollisions(vec.Names)

			var got []string
			for _, n := range vec.Names {
				if colliding[n] {
					got = append(got, n)
				}
			}
			// I nomi duplicati nel vettore producono una sola chiave nella
			// mappa: si confrontano gli insiemi, non le occorrenze.
			want := uniqueSorted(vec.Colliding)
			if !reflect.DeepEqual(uniqueSorted(got), want) {
				t.Errorf("CheckCollisions(%q) ha rilevato %v, atteso %v\n  fonte: %s",
					vec.Names, got, want, vec.Source)
			}
		})
	}
}

func TestExtensionVectors(t *testing.T) {
	v := loadVectors(t)

	for _, vec := range v.ExtensionVectors {
		t.Run(vec.Name, func(t *testing.T) {
			base, ext := SplitExtension(vec.Name)
			if base != vec.Base || ext != vec.Ext {
				t.Errorf("SplitExtension(%q) = (%q, %q), atteso (%q, %q)\n  fonte: %s",
					vec.Name, base, ext, vec.Base, vec.Ext, vec.Source)
			}
		})
	}
}

// uniqueSorted deduplica e ordina, per confrontare insiemi di nomi.
func uniqueSorted(in []string) []string {
	seen := make(map[string]bool, len(in))
	out := []string{}
	for _, s := range in {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}
