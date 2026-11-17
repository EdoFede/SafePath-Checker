// Package winpath prepara i path per le chiamate al filesystem su Windows.
//
// Il prefisso \\?\ non serve solo a superare MAX_PATH: disattiva anche la
// normalizzazione Win32, che altrimenti risolve "CON.txt" sul device console e
// toglie punti e spazi finali. Sono esattamente i nomi che il tool deve poter
// leggere e rinominare (Development guidelines §7.2). Go aggiunge il prefisso
// da solo soltanto oltre i 248 caratteri, quindi non basta.
//
// Il path prefissato va usato solo nelle chiamate al filesystem: report,
// journal e messaggi continuano a usare il path originale.
package winpath
