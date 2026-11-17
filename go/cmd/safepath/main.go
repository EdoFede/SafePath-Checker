// Comando safepath: validazione e correzione dei nomi di file e directory di
// un albero documentale sincronizzato fra sistemi eterogenei.
//
//	safepath scan        <path>...   cammina e valida            -> report
//	safepath auto-rename <path>...   cammina, valida e rinomina  -> report + azioni
//
// scan e' in sola lettura ed e' il dry run: non esiste un --dry-run su
// auto-rename, che duplicherebbe scan invitando all'errore di presumere il
// default opposto (Development guidelines §1).
package main

import (
	"os"

	"github.com/EdoFede/safepath-checker/go/internal/cli"
)

func main() {
	os.Exit(cli.Run(os.Args[1:], os.Stdout, os.Stderr))
}
