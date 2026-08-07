# Virto Area — File & Directory Naming Standard

**Status:** normative
**Applies to:** every file and directory stored in a Virto Area document tree and exposed through SMB, NFS or NextCloud sync.
**Profile in force:** **B — Extended Latin** (accented characters allowed; HFS+ residual risk formally accepted).
**Keywords:** MUST / MUST NOT / SHOULD / MAY are used as in RFC 2119.

---

## 0. Constants

Single source of truth. Any implementation MUST import these values rather than re-deriving them.

```yaml
# naming-constants.yaml
profile: B                          # extended Latin

length:
  prefix_reserved_chars: 50         # absolute path up to and including the sync-root separator
                                    # e.g. "C:\Users\nome.cognome\Virto Area\"
  windows_max_path_chars: 259       # MAX_PATH 260 minus NUL terminator
  relative_path_hard_chars: 209     # 259 - 50, absolute ceiling, never exceed
  suffix_reserve_chars: 25          # NextCloud conflict suffix only, see §4.2
  relative_path_max_chars: 180      # ENFORCED limit on the relative path
  dir_path_max_chars: 115           # directory portion only, no trailing separator
  file_name_max_chars: 64           # basename + extension
  dir_name_max_chars: 48            # single directory component
  component_max_bytes: 200          # UTF-8 bytes, measured after NFD, vs NAME_MAX 255
  max_depth: 6                      # directory levels below the sync root

unicode:
  normalization: NFC                # mandatory on write
  length_measurement: NFD           # worst case for both char and byte counts

case:
  policy: case-insensitive-unique   # collision check is casefold + NFC
```

Character-count checks are performed on the **NFD** form of the path: HFS+ clients decompose accented characters, and each decomposition adds one UTF-16 unit to the Windows path length.

---

## 1. Character set

### 1.1 Allowed (Profile B)

```
A-Z a-z 0-9
U+00C0–U+00D6  U+00D8–U+00F6  U+00F8–U+017F     # Latin-1 Supplement + Latin Extended-A letters
                                                # (U+00D7 × and U+00F7 ÷ excluded)
SPACE  -  _  .  (  )  ,
```

Regex character class, reusable verbatim (PCRE / JS / Python):

```
[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F]      # ALNUM
[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F ._\-(),]   # ALNUM + allowed punctuation
```

### 1.2 Forbidden

| Class | Characters | Reason |
|---|---|---|
| Windows / SMB illegal | `< > : " / \ | ? *` | rejected by Win32 and by SMB2/3 |
| Control | `U+0000`–`U+001F`, `U+007F` | illegal everywhere |
| URL / WebDAV unsafe | `# % ? + &` | breaks NextCloud WebDAV and share links |
| Shell unsafe | `$ \` ' " ! ; ^ ~ * [ ] { } |` | breaks rsync / tar / scripts |
| Non-Latin scripts | Greek, Cyrillic, CJK, emoji, `°`, `–`, `—`, `’`, `“ ”` | outside Profile B; typographic look-alikes cause silent duplicates |
| Standalone combining marks | `Mn` category | input MUST already be NFC |

---

## 2. Positional rules

A component MUST NOT:

| # | Rule | Rationale |
|---|---|---|
| 1 | start or end with a SPACE | Windows silently trims; SMB rejects |
| 2 | end with `.` | illegal in Win32 |
| 3 | start with `.` | hidden on POSIX; some NextCloud client exclude patterns |
| 4 | start with `._` | collides with AppleDouble resource forks |
| 5 | start with `-` | parsed as an option by CLI tools |
| 6 | start with `~` or `~$` | MS Office lock files, 8.3 short-name artifacts |
| 7 | contain two consecutive SPACEs | normalization ambiguity across clients |
| 8 | contain `..` | path traversal ambiguity |
| 9 | end with `.` `,` or SPACE | see 1, 2 |

A file component MUST carry exactly one extension, lowercase, as the last `.`-separated segment. `.tar.gz` is the only accepted double extension.

---

## 3. Reserved names

Matching is **case-insensitive** and applies **with or without extension** — `CON.txt` is illegal.

```yaml
windows_device_names:
  [CON, PRN, AUX, NUL, COM0..COM9, LPT0..LPT9, CLOCK$, CONIN$, CONOUT$]

platform_reserved:
  macos:      [.DS_Store, "Icon\r", .AppleDouble, .AppleDB, .AppleDesktop,
               .TemporaryItems, .Spotlight-V100, .fseventsd, .Trashes]
  nextcloud:  [.htaccess, .ocdata, .sync-exclude.lst, "*.part", "*.filepart"]
  samba:      [.snapshot, desktop.ini]
```

---

## 4. Length budget

### 4.1 Layout

```
|<------------------------ 259 chars (MAX_PATH - 1) ---------------------------->|
|<--- 50: prefix --->|<---------------- 209: relative path (hard) -------------->|
                     |<---------- 180: enforced budget ---------->|<-25: reserve>|
                                                                   conflict suffix
```

`prefix_reserved_chars = 50` covers the absolute path up to and including the sync-root separator, e.g. `C:\Users\nome.cognome\Virto Area\` (33 chars) — 17 chars of headroom for longer usernames or relocated sync roots.

### 4.2 Reserve composition

The reserve is sized on the **single largest affix**, not on the sum: these affixes are mutually exclusive in practice, since each applies to the original file name and never to an already-affixed one.

| Affix | Producer | Overhead | Covered |
|---|---|---|---|
| `_conflict-YYYYMMDD-HHMMSS` | NextCloud client | +25 | **yes — sizes the reserve** |
| `.<name>.~xxxxxx` | NextCloud client temp | +9 | yes |
| `.~lock.<name>#` | OnlyOffice / LibreOffice | +8 | yes |
| `~$<name>` | MS Office temp | +2 | yes |

If the reserve is exhausted, the NextCloud client **cannot create the conflict file and the local modification is lost**. This is the sole justification for the margin — it is not decorative.

> **Residual risk accepted.** A lock or temp affix applied to a file that is *already* a conflict copy (`.~lock.<name>_conflict-YYYYMMDD-HHMMSS.docx#`) would need 33 chars and can overflow a path at exactly 180. The scenario requires a conflict copy to be opened in OnlyOffice/Office while sitting on a maximum-length path; it is not prevented, only unlikely. Restore `suffix_reserve_chars: 33` (→ `relative_path_max_chars: 175`) if the audit ever reports it.

### 4.3 Enforced limits

All limits apply simultaneously.

| Metric | Limit | Measured on |
|---|---|---|
| Relative path from sync root | ≤ 180 chars | NFD |
| Directory portion of the path | ≤ 115 chars | NFD |
| File name (basename + extension) | ≤ 64 chars | NFD |
| Directory name (single component) | ≤ 48 chars | NFD |
| Any component | ≤ 200 bytes | UTF-8 of NFD |
| Depth below sync root | ≤ 6 levels | — |

---

## 5. Case and Unicode

**Case.** The NextCloud server is case-sensitive (Linux); Windows and macOS clients are case-insensitive. `Bilancio.xlsx` and `bilancio.xlsx` coexist server-side but produce a permanent, unresolvable sync conflict.

> Two names in the same directory MUST NOT be equal after `NFC(name).casefold()`.

**Unicode.** Profile B makes normalization a correctness issue, not a style issue.

| Layer | Behaviour |
|---|---|
| HFS+ (macOS ≤ 10.12, legacy volumes) | forces NFD on write |
| APFS (macOS ≥ 10.13) | normalization-insensitive, preserving |
| Linux / ext4 / NextCloud server | byte-transparent — NFC and NFD are two distinct files |
| NextCloud desktop client | no normalization, propagates what it receives |

Rules:

- Every write path (web UI, WebDAV, ingestion scripts, migration tooling) MUST normalize to **NFC** before storing.
- Collision detection MUST compare NFC forms.
- Length checks MUST use NFD (worst case).
- **Accepted residual risk:** an HFS+ client writing directly over SMB can still introduce NFD names. Detection is handled by the periodic non-conformance report, not prevented at write time.

---

## 6. Transport-specific constraints

### 6.1 SMB

- Disable SMB1 server- and client-side (`server min protocol = SMB2`).
- `mangled names = no` — 8.3 mangling injects `~` and produces unstable aliases.
- macOS maps Windows-illegal characters into the private-use area `U+F021`–`U+F03F` (`:` → `U+F022`): the file exists but is unreadable from Windows. §1 makes the mapping unnecessary; enable the `catia` VFS module only for legacy datasets.
- Shares serving macOS clients:

```ini
[area-docs]
   vfs objects = catia fruit streams_xattr
   fruit:metadata = stream
   fruit:resource = stream
   mangled names = no
   veto files = /.DS_Store/desktop.ini/.AppleDouble/.TemporaryItems/.Trashes/
   delete veto files = yes
```

### 6.2 NFS

- NFSv3 is byte-transparent: it accepts anything except `/` and NUL. It is the main vector for non-conformant names entering a shared dataset.
- A file created over NFS containing `:` or `?` becomes **unreachable over SMB** on the same export.
- Use NFSv4.1+; align client locales to `*.UTF-8`.
- **No unvalidated write path may reach an NFS export.** Validation belongs upstream, in the application or ingestion layer.

### 6.3 NextCloud

Config key names changed between NC 28 and NC 30 — **verify against the running version before applying**.

```php
// config/config.php  (NC 30+)
'forbidden_filename_characters' => [
    '\\','/','<','>',':','"','|','?','*','#','%','&','$','!','^','~','`',"'",
    ';','[',']','{','}','+',
],
'forbidden_filenames'           => ['.htaccess', '.ocdata'],
'forbidden_filename_basenames'  => ['con','prn','aux','nul',
                                    'com0','com1','com2','com3','com4',
                                    'com5','com6','com7','com8','com9',
                                    'lpt0','lpt1','lpt2','lpt3','lpt4',
                                    'lpt5','lpt6','lpt7','lpt8','lpt9'],
'forbidden_filename_extensions' => ['.part','.filepart'],
```

Behavioural notes:

- The desktop client flags Windows-illegal names as *invalid* and **refuses to sync them on every platform**, including Linux and macOS clients. This is intentional cross-client consistency, not a bug.
- Server-side versioning and trash add `.v<epoch>` / `.d<epoch>` (+11–12 chars) on Linux paths only — not budget-relevant.
- Check the client `sync-exclude.lst` before adding project-level patterns, to avoid duplicating existing filters (`.~lock.*`, `~$*`, `*.tmp`).

---

## 7. Reference validator

Normative implementation. The regexes in §8 are a convenience approximation for non-Python tooling; **this code wins on any disagreement**.

```python
"""Virto Area naming validator - Profile B (extended Latin)."""

import re
import unicodedata
from dataclasses import dataclass

RELATIVE_PATH_MAX_CHARS = 180
RELATIVE_PATH_HARD_CHARS = 209
DIR_PATH_MAX_CHARS = 115
FILE_NAME_MAX_CHARS = 64
DIR_NAME_MAX_CHARS = 48
COMPONENT_MAX_BYTES = 200
MAX_DEPTH = 6

ALLOWED_PUNCTUATION = set(" -_.(),")

WINDOWS_DEVICE_NAMES = re.compile(
    r"^(?i:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[0-9]|LPT[0-9])(?:\.|$)"
)

RESERVED_BASENAMES = {
    ".ds_store", "icon\r", ".appledouble", ".appledb", ".appledesktop",
    ".temporaryitems", ".spotlight-v100", ".fseventsd", ".trashes",
    ".htaccess", ".ocdata", ".sync-exclude.lst", ".snapshot", "desktop.ini",
}

FORBIDDEN_PREFIXES = ("._", "~$", ".", "-", "~")
FORBIDDEN_EXTENSIONS = (".part", ".filepart", ".tmp")


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


def _is_allowed_char(char: str) -> bool:
    """Profile B: ASCII alphanumerics, Latin-1/Latin-Ext-A letters, allowed punctuation."""
    if char in ALLOWED_PUNCTUATION:
        return True
    if "0" <= char <= "9" or "A" <= char <= "Z" or "a" <= char <= "z":
        return True
    if unicodedata.category(char) not in ("Lu", "Ll"):
        return False
    base = unicodedata.normalize("NFD", char)[0]
    return "A" <= base <= "Z" or "a" <= base <= "z"


def validate_component(name: str, is_directory: bool) -> list[Violation]:
    """Validate a single path component. Empty result means compliant."""
    violations: list[Violation] = []

    if unicodedata.normalize("NFC", name) != name:
        violations.append(Violation("CHR-002", f"not in NFC form: {name!r}"))

    decomposed = unicodedata.normalize("NFD", name)
    max_chars = DIR_NAME_MAX_CHARS if is_directory else FILE_NAME_MAX_CHARS
    code = "LEN-004" if is_directory else "LEN-003"

    if len(decomposed) > max_chars:
        violations.append(Violation(code, f"{len(decomposed)} chars, max {max_chars}"))
    if len(decomposed.encode("utf-8")) > COMPONENT_MAX_BYTES:
        violations.append(Violation(
            "LEN-005", f"{len(decomposed.encode('utf-8'))} bytes, max {COMPONENT_MAX_BYTES}"))

    for char in name:
        if not _is_allowed_char(char):
            violations.append(Violation("CHR-001", f"illegal character U+{ord(char):04X}"))
            break

    if name.startswith(" ") or name.endswith(" "):
        violations.append(Violation("POS-003", "leading or trailing space"))
    if name.endswith(".") or name.endswith(","):
        violations.append(Violation("POS-002", "trailing dot or comma"))
    if name.startswith("._"):
        violations.append(Violation("POS-004", "AppleDouble prefix"))
    elif name.startswith("~"):
        violations.append(Violation("POS-006", "leading tilde"))
    elif name.startswith("."):
        violations.append(Violation("POS-001", "leading dot"))
    elif name.startswith("-"):
        violations.append(Violation("POS-005", "leading dash"))
    if "  " in name:
        violations.append(Violation("POS-007", "consecutive spaces"))
    if ".." in name:
        violations.append(Violation("POS-008", "consecutive dots"))

    if WINDOWS_DEVICE_NAMES.match(name):
        violations.append(Violation("RSV-001", "Windows device name"))
    if name.lower() in RESERVED_BASENAMES:
        violations.append(Violation("RSV-002", "platform reserved name"))
    if not is_directory and name.lower().endswith(FORBIDDEN_EXTENSIONS):
        violations.append(Violation("RSV-003", "reserved extension"))

    return violations


def validate_relative_path(relative_path: str) -> list[Violation]:
    """Validate a full relative path (POSIX separators) from the sync root."""
    violations: list[Violation] = []
    decomposed = unicodedata.normalize("NFD", relative_path)

    if len(decomposed) > RELATIVE_PATH_MAX_CHARS:
        violations.append(Violation(
            "LEN-001", f"{len(decomposed)} chars, max {RELATIVE_PATH_MAX_CHARS}"))

    parts = [part for part in relative_path.split("/") if part]
    if not parts:
        return [Violation("PTH-001", "empty path")]

    directories, file_name = parts[:-1], parts[-1]

    if len(directories) > MAX_DEPTH:
        violations.append(Violation("LEN-006", f"depth {len(directories)}, max {MAX_DEPTH}"))
    dir_path_len = len(unicodedata.normalize("NFD", "/".join(directories)))
    if dir_path_len > DIR_PATH_MAX_CHARS:
        violations.append(Violation(
            "LEN-002", f"directory path {dir_path_len} chars, max {DIR_PATH_MAX_CHARS}"))

    for directory in directories:
        violations.extend(validate_component(directory, is_directory=True))
    violations.extend(validate_component(file_name, is_directory=False))

    return violations


def validate_directory_listing(names: list[str]) -> list[Violation]:
    """Detect names colliding after NFC + casefold, i.e. unsyncable pairs."""
    violations: list[Violation] = []
    seen: dict[str, str] = {}
    for name in names:
        key = unicodedata.normalize("NFC", name).casefold()
        if key in seen:
            violations.append(Violation("UNQ-001", f"{seen[key]!r} collides with {name!r}"))
        seen[key] = name
    return violations
```

---

## 8. Portable regexes

Approximation for shell, JS or Samba-side use. Anchored, applied to **one component at a time**.

```regex
# File component, max 64 chars
^(?!(?i:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$))(?![.\-~])(?!.*  )(?!.*\.\.)[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F](?:[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F ._\-(),]{0,62}[A-Za-z0-9\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u017F)_\-])?$

# Directory component, max 48 chars: replace {0,62} with {0,46}
```

---

## 9. Error codes

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
| `RSV-002` | platform reserved basename |
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

## 10. Test vectors

Regression suite for any implementation. `[]` means compliant.

| Input (relative path) | Expected codes |
|---|---|
| `10_Amministrazione/2026-08-06_verbale-cda.md` | `[]` |
| `20_Tecnico/relazione_città_v03.docx` | `[]` |
| `Offerta (rev. 2), Rossi.pdf` | `[]` |
| `Offerta n° 12/2024 – Rossi & C..pdf` | `CHR-001`, `POS-002` |
| `CON.docx` | `RSV-001` |
| `Riepilogo trimestrale .md` | `POS-003`, `POS-002` |
| `._appunti.md` | `POS-004` |
| `-verbale.pdf` | `POS-005` |
| `~$bilancio.xlsx` | `POS-006` |
| `report  finale.md` | `POS-007` |
| `backup 2024-01-15 12:30.tar.gz` | `CHR-001` |
| `citta\u0300.docx` (NFD) | `CHR-002` |
| `a/b/c/d/e/f/g/file.md` | `LEN-006` |
| `.DS_Store` | `POS-001`, `RSV-002` |
| listing `['Bilancio.xlsx', 'bilancio.xlsx']` | `UNQ-001` |

---

## 11. Recommended conventions

Not enforced; they improve legibility and sort order without affecting correctness.

```
Sortable directories:   10_Amministrazione/  20_Tecnico/  30_Commerciale/
ISO 8601 date first:    2026-08-06_verbale-cda.md
Versioning:             offerta_acme_v03.docx
Separators:             '_' between semantic blocks, '-' inside a block
Case:                   PascalCase or Titolo_Con_Underscore for directories,
                        lowercase for files
```

Correctness is guaranteed by the casefold uniqueness test in §5, never by the case convention.

---

## 12. Client baseline

The originally requested baseline (Windows 7, Debian 6, macOS 10.9 Mavericks) is out of support on all three platforms and imposes the worst constraint on every axis.

| Requested | Blocking issues | Required baseline |
|---|---|---|
| Windows 7 x64 (EOL 2020-01) | MAX_PATH 260 not liftable (no `LongPathsEnabled`); SMB capped at 2.1 (no encryption, no multichannel); **NextCloud desktop client 3.x unsupported** — last compatible line is 2.6, unmaintained | **Windows 10 22H2** minimum, **Windows 11 23H2+** preferred, `LongPathsEnabled=1` via GPO |
| Debian 6 "squeeze" (EOL 2016) | Samba 3.5 → SMB1 only; NFSv4.0; kernel 2.6.32; glibc/Qt too old for the NextCloud client | **Debian 12 "bookworm"** or **13 "trixie"** |
| macOS 10.9 Mavericks (EOL 2016) | HFS+ forced NFD normalization — primary cause of duplicates and sync conflicts; immature SMB2 client; NextCloud client unsupported | **macOS 12 Monterey** minimum, **13/14** preferred (APFS) |

Consequences of adopting the required baseline:

- **Long paths.** With `LongPathsEnabled` the Windows ceiling rises to 32 767, but the binding constraint moves to macOS `PATH_MAX` (1024 bytes) and to Explorer plus non-manifest-aware applications, which still fail past 260. The 180-char budget stays a **project rule**; long-path support is a safety net, not a licence for deeper trees.
- **APFS.** Stops new NFD names being generated; does not convert NFD names already present server-side. A one-off remediation pass over the existing dataset is still required.
- **SMB 3.1.1.** Enables in-transit encryption and multichannel, and allows SMB1 to be disabled fleet-wide.

---

## 13. Enforcement matrix

| Layer | Mechanism | Blocking |
|---|---|---|
| NextCloud web / WebDAV | `forbidden_*` config keys (§6.3) | yes |
| NextCloud desktop client | built-in Windows-name validation | yes (per-file, silent) |
| Samba | `veto files`, `mangled names = no` | partial |
| NFS export | none available at protocol level | no — validate upstream |
| Ingestion / migration scripts | `validate_relative_path()` (§7) | yes |
| Periodic audit | filesystem walk + `validate_directory_listing()` | no — reporting only |

The audit is the only control covering NFS writes and HFS+ NFD names, which are the two paths that cannot be blocked at write time under Profile B.

---

## 14. Open items

- Legacy dataset migration: rename strategy (automatic with mapping table vs assisted) and repair of internal document cross-references. Deferred.
- Audit cadence, report format and remediation SLA. Deferred.
- Verification of the actual `forbidden_*` config key names on the NextCloud version deployed in production.
