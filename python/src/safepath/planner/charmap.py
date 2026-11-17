"""Mappa di traslitterazione per la remediation dei caratteri fuori Profilo B.

QUESTO FILE E' PENSATO PER ESSERE EDITATO. Aggiungere una riga qui e'
sufficiente per rendere automaticamente correggibile un carattere che oggi
produce ``action = manual``: non c'e' altra logica da toccare.

Criteri:
  - la sostituzione deve essere composta solo da caratteri del Profilo B,
    verificato dal test ``test_charmap_produces_valid_chars``;
  - stringa vuota significa "rimuovi il carattere";
  - le sostituzioni conservano il senso del nome, non lo abbreviano: la tabella
    di rewrite di File naming Tech-rules §9 e' la fonte degli esempi.

I caratteri fuori profilo NON presenti in questa mappa non vengono indovinati:
l'entry diventa ``action = manual`` e il carattere compare nel riepilogo di fine
esecuzione, che e' il posto da cui partire per estendere la mappa.
"""

CHAR_MAP: dict[str, str] = {
    # --- Illegali su Windows / SMB (§2.3) ---
    "<": "",
    ">": "",
    ":": "h",  # "12:30" -> "12h30", esempio di §9
    '"': "",
    "/": "-",  # "12/2024" -> "12-2024", esempio di §9
    "\\": "-",
    "|": "-",
    "?": "",
    "*": "",
    # --- URL / WebDAV unsafe (§2.3) ---
    "#": "n",  # "#12" -> "n12", uso corrente come abbreviazione di "numero"
    "%": " pct",
    "+": " e ",  # usato come congiunzione nei nomi di cartella reali
    "&": "e",  # "Rossi & C." -> "Rossi e C.", esempio di §9
    # --- Shell unsafe (§2.3) ---
    "$": "",
    "`": "",
    "'": "",  # "L'ISOLANTE" -> "LISOLANTE"
    "!": "",  # "[DEF]!" -> "DEF", esempio di §9
    ";": ",",
    "^": "",
    "~": "",
    # "[DEF]!" -> "DEF" nella tabella §9: le parentesi quadre vengono rimosse,
    # non convertite in tonde. Le graffe seguono le quadre per coerenza.
    "[": "",
    "]": "",
    "{": "",
    "}": "",
    # --- Fuori profilo: punteggiatura tipografica (§2.3) ---
    "°": "",  # "n° 12" -> "n 12", esempio di §9
    # I trattini tipografici sono rimossi, non convertiti: in §9
    # "12/2024 – Rossi" diventa "12-2024 Rossi", dove il "-" viene dalla "/".
    "–": "",  # en dash
    "—": "",  # em dash
    "’": "",  # apostrofo tipografico
    "‘": "",
    "“": "",
    "”": "",
    "«": "",
    "»": "",
    "…": "",
    # --- Fuori profilo: simboli ricorrenti nei documenti amministrativi ---
    "€": " EUR",
    "£": " GBP",
    "@": " at ",
    "=": "-",
    "§": "par",
    "©": "(c)",
    "®": "(r)",
    "™": "(tm)",
    "µ": "u",
    "·": "-",
    "•": "-",
    # --- Controlli comuni (§2.3): rimossi, mai sostituiti con spazio ---
    "\t": " ",
    "\n": "",
    "\r": "",
}


def replacement(ch: str) -> tuple[str, bool]:
    """Restituisce la sostituzione prevista per un carattere fuori profilo.

    Il secondo elemento e' falso se il carattere non e' mappato: in quel caso non
    viene indovinato, rende l'entry ``action = manual`` (§3.2) e viene raccolto
    nel riepilogo di fine esecuzione.
    """
    if ch in CHAR_MAP:
        return CHAR_MAP[ch], True
    return "", False
