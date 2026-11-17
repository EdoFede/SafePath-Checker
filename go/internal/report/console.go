package report

import (
	"fmt"
	"io"
	"os"
	"strings"
	"unicode/utf8"

	"golang.org/x/term"
)

// Larghezza di riferimento quando stdout non e' un terminale, per rendere
// riproducibile l'elisione delle colonne nei test di parita' (§10).
const DefaultWidth = 120

// colour codes ANSI, usati solo quando UseColour lo consente.
const (
	ansiReset  = "\x1b[0m"
	ansiRed    = "\x1b[31m"
	ansiYellow = "\x1b[33m"
	ansiGreen  = "\x1b[32m"
	ansiDim    = "\x1b[2m"
)

// ConsoleOptions configura la resa della tabella.
type ConsoleOptions struct {
	Width     int // 0 = rilevata dal terminale, altrimenti forzata
	UseColour bool
}

// DetectConsoleOptions determina larghezza e colore dall'ambiente.
//
// Il colore va disattivato quando stdout non e' un TTY, quando NO_COLOR e'
// impostata o quando TERM=dumb. La tabella deve restare leggibile senza colore:
// nessuna informazione e' codificata nel solo colore (§4.1).
func DetectConsoleOptions(out *os.File) ConsoleOptions {
	isTTY := term.IsTerminal(int(out.Fd()))

	width := DefaultWidth
	if isTTY {
		if w, _, err := term.GetSize(int(out.Fd())); err == nil && w > 0 {
			width = w
		}
	}
	// COLUMNS permette ai test di fissare la larghezza senza un terminale.
	if v := os.Getenv("COLUMNS"); v != "" {
		var w int
		if _, err := fmt.Sscanf(v, "%d", &w); err == nil && w > 0 {
			width = w
		}
	}

	colour := isTTY &&
		os.Getenv("NO_COLOR") == "" &&
		os.Getenv("TERM") != "dumb" &&
		enableVT(out)

	return ConsoleOptions{Width: width, UseColour: colour}
}

// WriteConsole scrive la tabella e il riepilogo su w.
//
// La tabella e' l'output standard del programma ed e' sempre prodotta;
// diagnostica, avanzamento ed errori vanno su stderr, cosi' che una
// redirezione catturi la sola tabella (§4.1).
func WriteConsole(w io.Writer, r *Report, opts ConsoleOptions) error {
	if opts.Width <= 0 {
		opts.Width = DefaultWidth
	}

	writeHeader(w, r)

	if len(r.Rows) == 0 {
		// Il silenzio e' indistinguibile da un crash: quando non c'e' nulla da
		// riportare va detto esplicitamente (§4.1).
		fmt.Fprintln(w, "\nNessuna violazione rilevata.")
	} else {
		writeTable(w, r, opts)
	}

	writeSummary(w, r)
	writeUnmapped(w, r)
	return nil
}

// writeHeader emette l'intestazione che rende il report riproducibile a
// distanza di mesi: e' cio' che i test di parita' confrontano (§4.1, §10).
func writeHeader(w io.Writer, r *Report) {
	fmt.Fprintf(w, "safepath %s  |  schema %s  |  unicode %s  |  ruleset %s\n",
		r.ToolVersion, r.SchemaVersion, r.UnicodeVersion, r.RulesetVersion)
	fmt.Fprintf(w, "comando: %s  |  generato: %s\n", r.Command, r.GeneratedAt)
	fmt.Fprintf(w, "root: %s\n", strings.Join(r.Roots, ", "))
}

// column descrive una colonna della tabella.
type column struct {
	title     string
	truncable bool // path, detail ed excluded_by sono le colonne che si elidono
	value     func(Row) string
}

// tableColumns costruisce l'elenco di colonne in base alla forma del report.
// L'ordine e' fisso: colonne di findings prima, colonne azione appese (§3).
func tableColumns(r *Report) []column {
	cols := []column{
		{title: "root", value: func(x Row) string { return x.Root }},
		{title: "path", truncable: true, value: func(x Row) string { return x.Path }},
		{title: "type", value: func(x Row) string { return x.Type }},
		{title: "status", value: func(x Row) string { return x.Status }},
		{title: "codes", value: func(x Row) string { return strings.Join(x.Codes, " ") }},
		{title: "detail", truncable: true, value: func(x Row) string { return x.Detail }},
	}
	if r.WithActions {
		cols = append(cols,
			column{title: "action", value: func(x Row) string { return string(x.Action) }},
			column{title: "new_path", truncable: true, value: func(x Row) string { return x.NewPath }},
			column{title: "outcome", value: func(x Row) string { return string(x.Outcome) }},
		)
	}
	if r.Options.ShowExcluded {
		cols = append(cols, column{title: "excluded_by", truncable: true,
			value: func(x Row) string { return x.ExcludedBy }})
	}
	return cols
}

// writeTable emette la tabella allineata, elidendo le colonne elidibili quando
// il terminale e' stretto. Le larghezze sono l'unica parte dell'output
// autorizzata a variare fra esecuzioni (§4.1, §5).
func writeTable(w io.Writer, r *Report, opts ConsoleOptions) {
	cols := tableColumns(r)

	// Larghezza naturale di ogni colonna: il massimo fra titolo e valori.
	widths := make([]int, len(cols))
	for i, c := range cols {
		widths[i] = utf8.RuneCountInString(c.title)
		for _, row := range r.Rows {
			if n := utf8.RuneCountInString(c.value(row)); n > widths[i] {
				widths[i] = n
			}
		}
	}

	shrinkToFit(cols, widths, opts.Width)

	fmt.Fprintln(w)
	writeRow(w, cols, widths, func(i int) string { return cols[i].title }, "")
	writeRow(w, cols, widths, func(i int) string { return strings.Repeat("-", widths[i]) }, "")

	for _, row := range r.Rows {
		colour := ""
		if opts.UseColour {
			colour = statusColour(row)
		}
		writeRow(w, cols, widths, func(i int) string { return cols[i].value(row) }, colour)
	}
}

// shrinkToFit riduce le colonne elidibili finche' la tabella non entra nella
// larghezza disponibile. Le colonne root, status e codes non vengono mai
// troncate (§4.1).
func shrinkToFit(cols []column, widths []int, maxWidth int) {
	const sep = 2 // spazi fra colonne
	const minTruncable = 8

	total := func() int {
		t := sep * (len(cols) - 1)
		for _, x := range widths {
			t += x
		}
		return t
	}

	// Si riduce ciclicamente la colonna elidibile piu' larga: cosi' lo spazio
	// tolto e' distribuito invece di consumare per intero la prima colonna.
	for total() > maxWidth {
		widest, idx := 0, -1
		for i, c := range cols {
			if c.truncable && widths[i] > minTruncable && widths[i] > widest {
				widest, idx = widths[i], i
			}
		}
		if idx < 0 {
			return // nessuna colonna ulteriormente riducibile
		}
		widths[idx]--
	}
}

// writeRow emette una riga applicando troncamento e allineamento.
func writeRow(w io.Writer, cols []column, widths []int, value func(int) string, colour string) {
	cells := make([]string, len(cols))
	for i := range cols {
		cells[i] = pad(truncate(value(i), widths[i]), widths[i])
	}
	line := strings.TrimRight(strings.Join(cells, "  "), " ")

	if colour != "" {
		fmt.Fprintf(w, "%s%s%s\n", colour, line, ansiReset)
		return
	}
	fmt.Fprintln(w, line)
}

// truncate accorcia s a width caratteri segnando il taglio con "…" (§4.1).
func truncate(s string, width int) string {
	if utf8.RuneCountInString(s) <= width {
		return s
	}
	if width <= 1 {
		return "…"
	}
	runes := []rune(s)
	return string(runes[:width-1]) + "…"
}

// pad allinea a sinistra su width caratteri.
func pad(s string, width int) string {
	n := width - utf8.RuneCountInString(s)
	if n <= 0 {
		return s
	}
	return s + strings.Repeat(" ", n)
}

// statusColour sceglie il colore di una riga. Il colore distingue la gravita'
// ma non veicola informazione da solo: lo stato e' comunque nella colonna.
func statusColour(row Row) string {
	switch {
	case row.Action == ActionFailed, row.Outcome == OutcomeError:
		return ansiRed
	case row.Status == "violation":
		return ansiYellow
	case row.Status == "skipped", row.Status == "excluded":
		return ansiDim
	case row.Status == "ok":
		return ansiGreen
	}
	return ""
}

// writeSummary emette il riepilogo, che e' cio' che la maggior parte degli
// utenti legge davvero. Va su stdout insieme alla tabella (§4.1).
func writeSummary(w io.Writer, r *Report) {
	s := r.Summary
	fmt.Fprintf(w, "\nEsaminate %d voci: %d conformi, %d in violazione, %d saltate, %d escluse.\n",
		s.Examined, s.OK, s.Violations, s.Skipped, s.Excluded)

	if r.WithActions {
		fmt.Fprintf(w, "Rinominate %d, fallite %d, da correggere a mano %d.\n",
			s.Renamed, s.Failed, s.Manual)
	}
}

// writeUnmapped elenca i caratteri fuori profilo privi di sostituzione.
//
// E' il punto da cui partire per estendere charMap: senza questo elenco, le
// entry rimaste manual non dicono quale riga aggiungere alla mappa.
func writeUnmapped(w io.Writer, r *Report) {
	if len(r.Unmapped) == 0 {
		return
	}

	fmt.Fprintf(w, "\nCaratteri fuori profilo senza sostituzione prevista (%d):\n", len(r.Unmapped))
	for _, c := range r.Unmapped {
		fmt.Fprintf(w, "  %-4s U+%04X  %d occorrenze\n", string(c.Rune), c.Rune, c.Count)
	}
	fmt.Fprintln(w, "Per renderli correggibili, aggiungerli a internal/planner/charmap.go.")
}
