# File & Directory Naming Rules

Normative rules for every file and directory in a Virto Area document tree.
Profile **B — Extended Latin**. MUST / MUST NOT / SHOULD as in RFC 2119.

---

## 1. Constants

```yaml
profile: B

length:
  prefix_reserved_chars: 50         # absolute path up to and including the sync-root separator
  windows_max_path_chars: 259
  relative_path_hard_chars: 209     # 259 - 50, never exceed
  suffix_reserve_chars: 25          # NextCloud conflict suffix "_conflict-YYYYMMDD-HHMMSS"
  relative_path_max_chars: 180      # ENFORCED
  dir_path_max_chars: 115           # directory portion, no trailing separator
  file_name_max_chars: 64           # basename + extension
  dir_name_max_chars: 48
  component_max_bytes: 200          # UTF-8 of NFD, vs NAME_MAX 255
  max_depth: 6                      # directory levels below the sync root

unicode:
  normalization: NFC                # mandatory on write
  length_measurement: NFD           # worst case for char and byte counts

case:
  policy: case-insensitive-unique   # collision key = NFC(name).casefold()
```

`115 + 1 + 64 = 180`. All length limits apply simultaneously.

---

## 2. Character set

### 2.1 Allowed

```
A-Z  a-z  0-9
U+00C0–U+00D6  U+00D8–U+00F6  U+00F8–U+017F     # Latin-1 Supplement + Latin Extended-A letters
SPACE  -  _  .  (  )  ,
```

Reusable regex classes:

```
ALNUM   = [A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F]
ALLOWED = [A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F ._\-(),]
```

### 2.2 Explicitly permitted

Stated to remove any ambiguity — these are **valid** and MUST NOT be rejected or auto-corrected:

- **Uppercase letters** and any mix of upper/lower case: `Verbale CDA.docx`, `RELAZIONE.PDF`, `iPhone.png`
- **Single internal spaces**: `Offerta Rossi 2026.pdf`, `10 Amministrazione/`
- **Accented Latin characters**: `Città e Provincia.xlsx`, `Società.docx`
- **Parentheses and commas**: `Bilancio (bozza), rev 2.xlsx`
- **Internal dots**, including abbreviations: `Rossi e C. S.p.A.pdf`, `Nota n.12 del 3.4.2026.docx`, `archivio.tar.gz`

Case and dots are display concerns, not validity concerns. The only case-related constraint is the uniqueness rule in §5; the only dot-related constraints are the three in §3.

### 2.3 Forbidden

| Class | Characters |
|---|---|
| Windows / SMB illegal | `< > : " / \ \| ? *` |
| Control | `U+0000`–`U+001F`, `U+007F` |
| URL / WebDAV unsafe | `# % ? + &` |
| Shell unsafe | `` $ ` ' " ! ; ^ ~ * [ ] { } | `` |
| Out of profile | non-Latin scripts, emoji, `°` `–` `—` `’` `“` `”` |
| Standalone combining marks | Unicode category `Mn` |

---

## 3. Positional rules

A component MUST NOT:

| # | Rule | Code | Why it cannot be relaxed |
|---|---|---|---|
| 1 | start or end with a SPACE | `POS-003` | Windows silently trims, SMB rejects |
| 2 | end with `.` or `,` | `POS-002` | trailing dot is illegal in Win32 |
| 3 | start with `.` | `POS-001` | hidden file on POSIX; NextCloud exclude patterns |
| 4 | start with `._` | `POS-004` | collides with AppleDouble resource forks |
| 5 | start with `-` | `POS-005` | parsed as an option by CLI tools |
| 6 | start with `~` or `~$` | `POS-006` | MS Office lock files, 8.3 short-name artifacts |
| 7 | contain two consecutive SPACEs | `POS-007` | normalization ambiguity across clients |
| 8 | contain `..` | `POS-008` | path-traversal ambiguity; also produced by an abbreviation ending in a dot placed immediately before the extension |

Dots are otherwise unrestricted: any number of them may appear inside a component.

### 3.1 Extension detection

Deterministic rule, needed by §4 (reserved extensions) and by any remediation tooling. Given the last `.`-separated segment `S` of a file component:

```
extension = "." + S   if S matches ^[A-Za-z0-9]{1,10}$
extension = none      otherwise
```

Consequences:

| Component | Extension |
|---|---|
| `Rossi e C. S.p.A.pdf` | `.pdf` |
| `archivio.tar.gz` | `.gz` |
| `Nota n.12 del 3.4.2026.docx` | `.docx` |
| `Verbale rev. 2` | none (segment contains a space) |
| `Elenco soci S.p.A.` | invalid — trailing dot, `POS-002` |

The extension SHOULD be lowercase; uppercase is valid and MUST NOT be rewritten.

---

## 4. Reserved names

Case-insensitive.

```yaml
windows_device_names: [CON, PRN, AUX, NUL, CLOCK$, CONIN$, CONOUT$,
                       COM0..COM9, LPT0..LPT9]
reserved_basenames:   [.DS_Store, "Icon\r", .AppleDouble, .AppleDB, .AppleDesktop,
                       .TemporaryItems, .Spotlight-V100, .fseventsd, .Trashes,
                       .htaccess, .ocdata, .sync-exclude.lst, .snapshot, desktop.ini]
reserved_extensions:  [.part, .filepart, .tmp]
```

Matching scope:

- **Device names** are matched against the segment preceding the **first** dot, with or without anything following it: `CON`, `CON.txt` and `CON.rev 2.docx` are all illegal; `Documento CON allegati.pdf` and `precon.txt` are legal.
- **Reserved basenames** are matched against the whole component.
- **Reserved extensions** are matched against the extension as defined in §3.1.

---

## 5. Case and Unicode

- Two names in the same directory MUST NOT be equal after `NFC(name).casefold()`.
  The server is case-sensitive, the clients are not: a collision produces a permanent, unresolvable sync conflict.
  `Bilancio.xlsx` and `Bilancio 2026.xlsx` are fine; `Bilancio.xlsx` and `bilancio.xlsx` are not.
- Every write path MUST normalize to **NFC** before storing.
- Collision detection compares **NFC** forms; length checks use **NFD** (one extra code point per accent, up to 3 bytes per character).

---

## 6. Portable regex

Anchored, applied to **one component at a time**. Covers §2 (character set) and §3 (positional rules) plus the device names of §4.

**Not covered — implement separately:** length limits in characters and bytes (§1), extension detection (§3.1), reserved basenames and extensions (§4), NFC normalization check (§5), case-insensitive uniqueness (§5).

```regex
# File component, max 64 chars
^(?!(?i:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$))(?![.\-~])(?!.*  )(?!.*\.\.)[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F](?:[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F ._\-(),]{0,62}[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F)_\-])?$

# Directory component, max 48 chars: replace {0,62} with {0,46}
```

---

## 7. Error codes

| Code | Meaning |
|---|---|
| `CHR-001` | character outside Profile B |
| `CHR-002` | name not in NFC form |
| `POS-001` | leading dot |
| `POS-002` | trailing dot or comma |
| `POS-003` | leading or trailing space |
| `POS-004` | AppleDouble prefix `._` |
| `POS-005` | leading dash |
| `POS-006` | leading tilde |
| `POS-007` | consecutive spaces |
| `POS-008` | consecutive dots |
| `RSV-001` | Windows device name |
| `RSV-002` | reserved basename |
| `RSV-003` | reserved extension |
| `LEN-001` | relative path too long |
| `LEN-002` | directory portion too long |
| `LEN-003` | file name too long (chars) |
| `LEN-004` | directory name too long (chars) |
| `LEN-005` | component too long (bytes, NFD) |
| `LEN-006` | depth exceeded |
| `UNQ-001` | case-insensitive collision |
| `PTH-001` | empty path |

---

## 8. Test vectors

`[]` means compliant.

| Input (relative path) | Expected codes |
|---|---|
| `Amministrazione/Verbale CDA 2026-08-06.md` | `[]` |
| `Tecnico/Relazione Città (rev 3).docx` | `[]` |
| `Offerta Rossi e C. S.p.A.pdf` | `[]` |
| `Nota n.12 del 3.4.2026.docx` | `[]` |
| `RELAZIONE FINALE.PDF` | `[]` |
| `Documento CON allegati.pdf` | `[]` |
| `archivio.tar.gz` | `[]` |
| `Elenco soci S.p.A..pdf` | `POS-008` |
| `Elenco soci S.p.A.` | `POS-002` |
| `Offerta n° 12/2024 – Rossi & C.pdf` | `CHR-001` |
| `CON.rev 2.docx` | `RSV-001` |
| `Riepilogo trimestrale .md` | `POS-003` |
| `._appunti.md` | `POS-004` |
| `-verbale.pdf` | `POS-005` |
| `~$bilancio.xlsx` | `POS-006` |
| `Report  finale.md` | `POS-007` |
| `Backup 2024-01-15 12:30.tar.gz` | `CHR-001` |
| `Città.docx` written as NFD | `CHR-002` |
| `a/b/c/d/e/f/g/file.md` | `LEN-006` |
| `.DS_Store` | `POS-001`, `RSV-002` |
| listing `['Bilancio.xlsx', 'bilancio.xlsx']` | `UNQ-001` |

---

## 9. Rewrite examples

Reference transformations for remediation tooling. Case, spaces and internal dots are preserved; only the violating element is changed.

| Non-compliant | Violation | Compliant |
|---|---|---|
| `Offerta n° 12/2024 – Rossi & C. S.p.A.pdf` | `°`, `/`, `–`, `&` | `Offerta n 12-2024 Rossi e C. S.p.A.pdf` |
| `Elenco soci S.p.A..pdf` | `..` before extension | `Elenco soci S.p.A.pdf` |
| `Elenco soci S.p.A.` | trailing dot | `Elenco soci S.p.A` |
| `Backup 2024-01-15 12:30.tar.gz` | `:` | `Backup 2024-01-15 12h30.tar.gz` |
| `Documento (rev.3) [DEF]!.docx` | `[ ]`, `!` | `Documento (rev.3) DEF.docx` |
| `CON.docx` | Windows device name | `Contratto CON.docx` |
| `Riepilogo trimestrale .md` | trailing space | `Riepilogo trimestrale.md` |
| `Bilancio.xlsx` + `bilancio.xlsx` | casefold collision | `Bilancio.xlsx` + `Bilancio 2025.xlsx` |
