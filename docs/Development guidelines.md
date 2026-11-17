# Naming Tools — Development Notes

Implementation notes for `safepath`, the compliance checker and renamer, targeting **Windows / macOS / Linux** with byte-identical results across all platforms and both implementations (**Go** and **Python**).

Naming rules themselves are out of scope here — see `File naming Tech-rules.md`, which is normative for codes, limits and remediation.

---

## 1. Architecture

**One binary, two subcommands.** No intermediate file, no separate plan step.

```
safepath scan        <path>...    walk + validate                       ──► report
safepath auto-rename <path>...    walk + validate + rename + re-read    ──► report + actions
```

`scan` is read-only. `auto-rename` performs the same walk and validation and, as it descends, renames what it finds non-compliant, re-reading each renamed entry to confirm the result (§9).

There is no dry-run flag: **`scan` is the dry run.** `auto-rename` writes by definition, and a `--dry-run` on it would only duplicate `scan` while inviting the mistake of assuming the reverse default.

The separation that matters is **internal**, not between processes:

```
package walker   filesystem traversal, OS-specific   ──► []Entry
package rules    validation, no filesystem access    ──► []Violation
package planner  rename resolution                   ──► []Operation
package report   accumulation and serialisation      ──► console / CSV / JSON
```

`rules` never touches the filesystem. All OS divergence is confined to `walker`. `planner` computes target names from `[]Violation` and remains filesystem-free except for the collision lookups of §8.2, which are injected. The test suite feeds synthetic `Entry` values directly, so identical cross-platform results are a property of the design rather than of the workflow.

Both subcommands drive the same pipeline; `auto-rename` adds the mutation stage between `planner` and `report`. The report of a `scan` and the report of an `auto-rename` over the same tree MUST agree on the findings columns — the rename columns are additive (§3).

The **manifest** — a JSONL serialisation of `[]Entry` — is an optional output (`--emit-manifest`), not part of the normal workflow. It is worth producing for two purposes: archiving the state a report refers to, and diffing consecutive runs to see what changed in the tree. It is also the transport used by the cross-implementation parity tests (§10).

---

## 2. Command-line interface

```
safepath scan        [options] <path>...
safepath auto-rename [options] <path>...
```

### 2.1 Path arguments

- **One or more paths per invocation.** `safepath scan 10\ Amministrazione 20\ Tecnico` scans two of the five directories present without touching the other three.
- Paths are **relative to the current working directory** at launch. Absolute paths are accepted, but relative is the documented form.
- A path argument may be a directory (walked recursively) or a single file (validated alone).
- Each argument is its own **scan root**: depth (`LEN-006`) and relative-path length (`LEN-001`, `LEN-002`) are counted from the argument, not from the current directory nor from the filesystem root. This is the same "sync root" the rules document refers to, and it makes `safepath scan 10\ Amministrazione` from the sync root and `safepath scan .` from inside it produce the same codes for the same files.
- The scan root itself is not validated as a component — only its contents. A user pointing the tool at an existing directory is not asking for that directory's own name to be judged.
- **Arguments are processed in the order given**, and each is walked to completion before the next. Within a root, ordering is the byte order of §5 (Determinism contract). Repeated or nested arguments (`a` and `a/b`) MUST be detected before the walk and rejected with exit 2 rather than producing duplicate rows.
- Report paths are emitted relative to their scan root, with a `root` column identifying which argument they belong to (§3).

### 2.2 Options

| Option | Applies to | Effect |
|---|---|---|
| `--show-ok` | both | include compliant entries in the report (§3.3) |
| `--exclude <glob>` | both | skip entries matching a glob; repeatable (§2.3) |
| `--exclude-regex <re>` | both | skip entries matching a regex; repeatable (§2.3) |
| `--show-excluded` | both | include excluded entries in the report (§3.4) |
| `--output-csv <file>` | both | write the report as CSV (§4.2) |
| `--output-json <file>` | both | write the report as JSON (§4.3) |
| `--emit-manifest <file>` | both | JSONL dump of `[]Entry` (§1) |

`--output-csv` and `--output-json` are independent and may be given together to write both files in one run. Neither suppresses the console table (§4.1), which is always produced.

Reject a second occurrence of the same output option with exit 2 instead of silently taking the last one — a scripted `--output-csv a.csv --output-csv b.csv` is a bug in the caller, not a preference. The exclusion options and the two display flags are the exceptions: the exclusions are repeatable by design, and a repeated boolean flag is harmless.

### 2.3 Exclusion patterns

Two options, both repeatable, both additive:

```
--exclude <glob>          glob syntax
--exclude-regex <re>      regular expression
```

**Every occurrence of either option contributes**, and an entry is excluded if it matches **any** pattern from **either** set. The two sets are never in competition and never override one another: exclusions only ever add. There is no corresponding "include" option to re-admit an entry — a union of exclusions is predictable regardless of argument order, and an include/exclude interplay is not. Order of the arguments never affects the outcome.

No occurrence of either option means no user exclusions.

```
safepath scan 10\ Amministrazione \
  --exclude '*.tmp' --exclude 'Archivio 20*' \
  --exclude-regex '^~\$' --exclude-regex '\.(bak|old)$'
```

#### Glob — `--exclude`

- Syntax: `*`, `?`, `[…]`. `*` does not cross `/`; use `**` for that.
- Matched against the component name **and** the path relative to the scan root. A pattern containing `/` is matched against the relative path only — `--exclude '*.tmp'` catches the file anywhere, `--exclude 'Archivio/*.tmp'` only under `Archivio`.
- The whole string must match, not a substring: `--exclude 'bozza'` does not exclude `bozza finale.docx`. Use `--exclude '*bozza*'`.

#### Regex — `--exclude-regex`

For what globs cannot express: alternation, anchoring, quantifiers, character classes by property.

- Syntax: **RE2** (Go `regexp`, Python `re` restricted to the common subset). Backreferences and lookaround are RE2-incompatible and MUST be rejected at argument-parsing time with exit 2, in **both** implementations — Python would otherwise accept a pattern Go cannot compile, and the parity guarantee of §10 would hold only until someone used one.
- **Unanchored by default**, i.e. a search, not a full match: `--exclude-regex '\.bak$'` behaves as expected, and full-string matching stays available via `^…$`. This is where regex deliberately differs from glob; the two options have different semantics because they serve different needs, and the difference is documented rather than papered over.
- Matched against the component name **and** the path relative to the scan root, like globs. A pattern containing `/` is matched against the relative path only.
- An invalid regex is exit 2 with the compiler's message and the offending pattern echoed back. Never silently treat an uncompilable pattern as a literal string.

#### Semantics common to both

- Matching is **case-insensitive**, on `casefold(NFC(pattern))` against `casefold(NFC(name))` — consistent with §6.2 and with the case-insensitive clients the tool exists to protect. For the regex, apply the case-insensitive flag rather than pre-folding the pattern, and normalise the pattern to NFC before compiling: a pattern typed on macOS may arrive in NFD and would otherwise not match its own target.
- Excluding a **directory excludes its entire subtree**, and the subtree is not walked at all. This is what makes `--exclude 'node_modules'` cheap rather than merely quiet. With `--show-excluded` the directory is reported as one excluded row; its unwalked contents are not enumerated (§3.4).
- Excluded entries are absent from the report unless `--show-excluded` is given, and always absent from the exit-code computation and — in `auto-rename` — from renaming. They are counted in the run summary (§4.1) so that a suspiciously small report is traceable to its cause.
- Exclusions apply to `auto-rename` identically. An excluded entry is never renamed, **including as a collateral effect**: a collision group (§8.3) whose members include an excluded entry must still account for that entry when checking target availability. Excluded means "do not touch", not "does not exist".
- Matching runs against the name **as found on disk**, before any rename. In `auto-rename` a pattern therefore selects what the user sees in the tree, not a name the tool is about to invent.

These are additive to the built-in bookkeeping skips of §7.3, which are unconditional and not user-configurable. A bookkeeping skip is not an exclusion: it is never reported, not even under `--show-excluded`.

---

## 3. Report model

One report model, two shapes. `scan` and `auto-rename` produce the **same rows and the same findings columns**; `auto-rename` appends the action columns. A consumer written against the `scan` shape must keep working against an `auto-rename` report, which is why the extra columns are appended and never interleaved.

### 3.1 Findings columns — both subcommands

| Column | Content |
|---|---|
| `root` | the path argument this row belongs to, verbatim as given on the command line |
| `path` | path relative to `root`, NFC, `/` separators, no leading `./` |
| `type` | `file` \| `dir` |
| `status` | `violation` \| `ok` \| `skipped` \| `excluded` |
| `codes` | violation codes (§ rules doc), sorted, deduplicated |
| `detail` | human-readable Italian description of the finding |

`codes` is the machine-readable field and `detail` the human one; never parse `detail`. A row with several violations stays **one row** with several codes — one row per entry, always, so that row counts mean something.

Order the codes by their identifier, not by discovery: an entry violating both `POS-001` and `RSV-002` reports `POS-001, RSV-002` on every platform and in both implementations.

### 3.2 Action columns — `auto-rename` only

| Column | Content |
|---|---|
| `action` | `rename` \| `none` \| `manual` \| `failed` |
| `new_path` | resulting path relative to `root`, NFC; empty unless `action = rename` |
| `outcome` | `ok` \| `unchanged` \| `error` \| `skipped` |
| `outcome_detail` | Italian description of the outcome, or the reason for `manual` / `failed` |

The pair is deliberately redundant: `action` records **what the tool decided to do**, `outcome` **what the filesystem confirmed** after re-reading (§9.3). They disagree exactly when something went wrong, and that disagreement is the most important information in the report.

| `action` | `outcome` | Meaning |
|---|---|---|
| `rename` | `ok` | renamed, and the re-read confirms the new name |
| `rename` | `error` | rename attempted, re-read did not confirm it — **investigate** |
| `none` | `unchanged` | compliant entry, nothing to do (only visible with `--show-ok`) |
| `manual` | `skipped` | non-compliant but not automatically fixable: non-UTF-8 name (§7.1), or no compliant target available (§8.3) |
| `failed` | `error` | rename attempted and refused by the filesystem: locked, permissions, collision |

`codes` keeps describing the **original** state even when the rename succeeded. The report documents what was found, not what remains; a report whose findings columns emptied out as a side effect of fixing them would be useless as an audit record. To see the tree after remediation, run `scan` again — that is what it is for.

### 3.3 `--show-ok`

Default: only rows with `status` other than `ok` are emitted. With `--show-ok`, compliant entries are emitted as well, with `status = ok`, empty `codes`, and — under `auto-rename` — `action = none`, `outcome = unchanged`.

The flag changes **which rows are emitted, and nothing else**: not the column set, not the ordering, not the exit code. Every output format honours it identically. On a large tree it turns a short report into one row per entry, so it stays opt-in.

`skipped` rows (symlinks, cross-device entries, unreadable directories — §7.3) are **not** `ok` and are always emitted, regardless of the flag. Something the tool could not examine is a finding.

### 3.4 `--show-excluded`

Default: entries matched by `--exclude` or `--exclude-regex` produce no row at all. With `--show-excluded`, they are emitted with `status = excluded`, empty `codes`, and — under `auto-rename` — `action = none`, `outcome = skipped`.

The purpose is diagnosing the patterns themselves. An exclusion that is subtly too broad is invisible by construction: the report simply gets shorter, and nothing indicates that a whole branch of the tree went unexamined. This flag makes the pattern's effect auditable, and it is the first thing to reach for when a report looks implausibly clean.

Two columns exist for that diagnosis:

| Column | Content |
|---|---|
| `excluded_by` | the pattern that matched, verbatim as given on the command line |
| `detail` | which option it came from — `--exclude` or `--exclude-regex` |

`excluded_by` is present only when `--show-excluded` is given, and holds the **first** matching pattern in command-line order (globs before regexes when both were supplied). First rather than all: the question being answered is "which of my patterns is doing this?", and one answer per row keeps the column readable. Evaluation may still short-circuit on the first match.

Interactions, all deliberate:

- **`--show-excluded` does not un-exclude anything.** Excluded entries are still never renamed, still never counted toward the exit code. The flag changes reporting only — it is a lens, not an override.
- An **excluded directory** yields exactly one row, for the directory itself. Its contents remain unwalked (§2.3): reporting them would require walking a subtree the user asked the tool to skip, and on a `node_modules`-sized directory that would cost more than the whole rest of the run. The row for the directory is sufficient to explain everything missing beneath it.
- **Independent of `--show-ok`.** The two flags govern disjoint sets of rows and compose without interacting: neither implies the other, and giving both emits every entry the walk produced.
- Excluded rows sort into the report in normal path order (§5); they are not grouped at the end.

---

## 4. Output formats

The console table is the **standard output of the program** and is always produced. File outputs are additional and opt-in, requested per format:

```
safepath scan 10\ Amministrazione --output-csv report.csv --output-json report.json
```

All three carry the same rows, the same columns and the same order (§5). They differ only in presentation: the console table is formatted for reading, the files for consumption.

### 4.1 Console table

Written to **stdout**. Diagnostics, progress and errors go to **stderr**, so that `safepath scan … > out.txt` captures the table alone.

- A column-aligned table, one row per entry, in the order of §5.
- Columns are elided rather than wrapped when the terminal is narrow: `path`, `detail` and `excluded_by` are the truncating columns, `root`, `status` and `codes` are never truncated. A truncated cell is marked with `…`. Column widths are the one part of the output allowed to vary between runs.
- The `excluded_by` column appears only under `--show-excluded` (§3.4).
- Colour is used to distinguish severity and MUST be disabled when stdout is not a TTY, when `NO_COLOR` is set, or when `TERM=dumb`. The table MUST be fully legible without colour: never encode information in colour alone.
- The table is preceded by a header identifying the tool version, `schema_version`, `unicode_version` and `ruleset_version` (§10), and followed by a **summary**: entries examined, compliant, in violation, skipped, excluded, and — for `auto-rename` — renamed, failed and manual.

The summary is what most users will actually read. It goes to stdout with the table.

When there is nothing to report, say so explicitly (`Nessuna violazione rilevata.`) rather than printing an empty table. Silence is indistinguishable from a crash.

### 4.2 CSV

`--output-csv <file>`. RFC 4180.

| Aspect | Rule |
|---|---|
| Encoding | UTF-8 **with BOM** |
| Line ending | `\r\n` |
| Separator | `,` |
| Quoting | minimal — only fields containing `,`, `"`, `\r` or `\n`; `"` escaped as `""` |
| Header row | always present, column names exactly as in §3 |
| Multi-value `codes` | space-separated inside one field: `POS-001 RSV-002` |
| Empty values | empty field, never `NULL` or `-` |
| `excluded_by` column | present only with `--show-excluded`, appended last (§3.4) |

The column set is otherwise fixed and does not vary with the data: `--show-ok` adds rows, never columns. `excluded_by` is the single exception, and it is appended after the action columns so that the prefix of the header stays stable across every invocation — a consumer reading columns positionally keeps working.

Two deliberate departures from the rest of the document. The **BOM** is required because Excel otherwise reads UTF-8 as the system ANSI codepage and mangles every accented name — precisely the names this tool exists to find. **CRLF** is what RFC 4180 specifies. Both are properties of the CSV writer only: they MUST NOT leak into the JSON writer, the manifest or the console, and the CSV file must be written in binary mode with the line ending applied explicitly, never left to the platform (§5).

Never let a spreadsheet's expectations reach further than the CSV file. In particular, do not prefix fields with `'` or `=` to influence Excel's parsing.

### 4.3 JSON

`--output-json <file>`. A single JSON document, not JSONL — the report is consumed whole, and one document is what a caller's `json.load` expects. (The manifest, which is a stream, stays JSONL.)

```json
{
  "schema_version": "1",
  "ruleset_version": "…",
  "unicode_version": "…",
  "tool_version": "…",
  "command": "auto-rename",
  "generated_at": "2026-08-07T09:14:22Z",
  "roots": ["10 Amministrazione", "20 Tecnico"],
  "options": {"show_ok": false, "show_excluded": true,
              "exclude": ["*.tmp"], "exclude_regex": ["\\.(bak|old)$"]},
  "summary": {"examined": 1284, "ok": 1190, "violations": 88, "skipped": 6,
              "excluded": 12, "renamed": 84, "failed": 2, "manual": 2},
  "entries": [
    {"root": "10 Amministrazione", "path": "Verbali/Elenco soci S.p.A..pdf",
     "type": "file", "status": "violation", "codes": ["POS-008"],
     "detail": "…", "action": "rename", "new_path": "Verbali/Elenco soci S.p.A.pdf",
     "outcome": "ok", "outcome_detail": "…"},
    {"root": "10 Amministrazione", "path": "Verbali/bozza.bak",
     "type": "file", "status": "excluded", "codes": [], "detail": "--exclude-regex",
     "excluded_by": "\\.(bak|old)$", "action": "none", "outcome": "skipped",
     "outcome_detail": "…"}
  ]
}
```

- UTF-8 **without** BOM, `\n` line endings, keys sorted within each object.
- `codes` is an **array**, not a string — this is the format for machines, and the CSV flattening of §4.2 is a concession to a text format, not the model.
- The four action fields are present only for `auto-rename`. Absent, not null, under `scan`: their absence is how a consumer tells the two shapes apart.
- `excluded_by` is present only on rows with `status = excluded`, and only under `--show-excluded`.
- `options` echoes the exclusion patterns **as given on the command line**, unfolded and unnormalised, each option in its own array. A report that does not record which patterns produced it cannot be interpreted six months later, and the two lists must stay separate: a glob and a regex that look alike do not mean alike.
- `entries` is always an array, empty if nothing was reported. The header and summary are emitted even then.
- Do not escape non-ASCII (`ensure_ascii=False` in Python, which is Go's default): the accented names must stay readable in the file.

The header fields are what make a report reproducible months later, and the parity tests compare them (§10).

---

## 5. Determinism contract

Anything below that differs between two runs is a bug.

| Aspect | Rule |
|---|---|
| Path separator in reports and manifest | always `/`, never `\` |
| Path form in reports and manifest | NFC, relative to the scan root, no leading `./` |
| Sort order | byte order of the UTF-8 NFC path. In Go, plain `<` on `string`; in Python, plain `<` on `str` — codepoint order and UTF-8 byte order coincide, so both agree |
| Report row order | scan roots in command-line order; within a root, byte order of the path. Never discovery order, never `readdir` order |
| Report column order | fixed, as listed in §3; findings columns first, action columns appended |
| Code order within a row | sorted by code identifier, deduplicated |
| Locale | never used. No `strings.ToLower` with locale, no `locale.strcoll`, no `time.Local` |
| Timestamps | UTC, RFC 3339, only in metadata fields — never in identifiers or suffixes |
| JSON output | UTF-8 without BOM, `\n` line endings, sorted keys |
| Map/dict iteration | never emitted directly — Go randomizes map order by design; always sort first |
| Floating point | not used anywhere |

Two `scan` runs over an unchanged tree MUST produce byte-identical CSV and JSON. The console table is exempt only in its column widths, which adapt to terminal width (§4.1).

Ordering has one consequence worth stating: because rows come out sorted rather than in discovery order, **the report cannot be streamed row-by-row as the walk proceeds**. Accumulate, sort, then emit. This is affordable — a row is small, and the trees in scope are documents, not filesystems.

Write the reports, the manifest and all outputs in binary mode to avoid Windows CRLF translation. CSV is the exception, and a deliberate one (§8.2).

---

## 6. Unicode

### 6.1 Table pinning

Both implementations MUST declare the Unicode version they were built against, and the version MUST appear in the report header. Two runs with different tables are not comparable.

| | Go | Python |
|---|---|---|
| Normalization | `golang.org/x/text/unicode/norm` | `unicodedata2` (**not** stdlib `unicodedata`) |
| Case folding | `golang.org/x/text/cases.Fold()` | `str.casefold()` |
| Version pinning | `go.mod` pins `x/text` | `requirements.txt` pins `unicodedata2` |

Stdlib `unicodedata` is bound to the CPython build: 3.11 and 3.13 ship different tables. `unicodedata2` decouples them and is the only way to match a pinned Go build.

Normalization of already-assigned characters is stable across Unicode versions by policy; **category lookups and case folding are not**. The risk surface is `unicodedata.category()` (used for the combining-mark check) and folding, not NFC itself.

### 6.2 Case folding, not lowercasing

`strings.ToLower` (Go) and `str.lower()` (Python) are **not** equivalent to full case folding and MUST NOT be used for the collision key.

```
ß      →  lower: ß      fold: ss
ﬁ      →  lower: ﬁ      fold: fi
İ      →  lower: i̇      fold: i̇
K (U+212A) → lower: k   fold: k
```

Profile B rejects most of these as `CHR-001`, but the collision check runs on the **pre-remediation dataset**, which contains arbitrary legacy names. Full folding is required there.

Collision key: `casefold(NFC(name))`. Compare within a single directory only.

### 6.3 NFC vs NFD

- Reports and manifest store NFC.
- Length checks are computed on NFD (worst case) — see the rules document.
- The walker MUST record whether the on-disk name was already NFC. Converting silently would hide `CHR-002` findings, which are exactly the macOS/HFS+ artifacts the audit exists to detect.

Suggested manifest fields: `path` (NFC) plus `nfc_normalized: true|false`.

---

## 7. Path handling

### 7.1 Non-UTF-8 names (Linux)

Linux filenames are byte strings with no encoding guarantee. Both languages surface this differently:

- **Go**: `string` holds arbitrary bytes; invalid sequences survive but JSON encoding will replace them with U+FFFD.
- **Python**: `os.scandir()` returns `str` with `surrogateescape`; lone surrogates cannot be serialised to JSON.

Neither is representable in JSON. Add a fallback field:

```json
{"path": "<lossy UTF-8 rendering>", "path_b64": "<raw bytes, base64>", "valid_utf8": false}
```

When `valid_utf8` is false, `scan` emits `CHR-001` without further analysis, and `auto-rename` reports the entry as `action = manual` (§3.2) rather than attempting to construct a target name from bytes it cannot interpret.

### 7.2 Windows long paths

Even with the 180-char budget, the walker may traverse pre-remediation trees that exceed `MAX_PATH`.

- Go applies the `\\?\` prefix automatically for absolute paths in the `os` package.
- Python needs `LongPathsEnabled=1` **and** a manifest-aware interpreter, or an explicit `\\?\` prefix.

The `\\?\` form requires backslashes, an absolute path, and no `.` or `..` components — normalise before prefixing. Verify long-path behaviour explicitly in the test suite; it is the most common source of Go/Python divergence on Windows.

macOS `PATH_MAX` is 1024 bytes and cannot be lifted — it becomes the binding constraint once Windows long paths are enabled.

### 7.3 Traversal

- **Do not follow symlinks, junctions or reparse points.** Record and skip. Following them breaks depth counting and can loop.
- **Do not cross filesystem boundaries.** Compare device IDs; on Windows use the volume serial number.
- Depth is counted relative to the scan root — the path argument — not to the filesystem root and not to the current directory (§2.1).
- Skip client and server bookkeeping: `.nextcloud`, `.sync_*.db`, `.owncloudsync.log*`, `.~lock.*`, `~$*`, `*.part`, `*.filepart`, `files_versions/`, `files_trashbin/`. These are unconditional and independent of `--exclude` (§2.3).
- An unreadable directory is reported as `status = skipped` with the reason, and the walk continues. One permission error does not abort a run.
- Enumeration order from `readdir` differs across ext4, NTFS and APFS. **Sort every directory listing** before processing it — this is what makes the rename order of `auto-rename`, and not merely the report order, deterministic.

---

## 8. Rename hazards

Everything in this section applies to `auto-rename`. `scan` never writes.

### 8.1 Case-only rename

`Bilancio.xlsx` → `bilancio.xlsx` on NTFS, APFS or HFS+ is either rejected, silently ignored, or succeeds depending on filesystem and OS version. Never rely on it.

Mandatory two-step:

```
Bilancio.xlsx  →  Bilancio.xlsx.safepath-<hash>  →  bilancio.xlsx
```

Requirements on the temporary name:

- **Deterministic** — derived from a hash of the target path, so a crashed run can be resumed and the orphan recognised.
- Same directory (avoids `EXDEV`).
- Recognisable prefix, so a recovery pass can find and finish interrupted operations.
- Verify the temp name does not itself exist before use.

`auto-rename` must be crash-tolerant: on startup, scan for orphaned `*.safepath-*` entries and either complete or roll back. Note that the temporary name is itself non-compliant — the walk MUST skip `*.safepath-*` entries rather than report them, or an interrupted run pollutes the next report with its own debris.

### 8.2 Case-insensitive collisions during rename

On a case-insensitive filesystem, renaming `A.txt` to `b.txt` when `B.txt` exists **overwrites silently** — Go's `os.Rename` and Python's `os.replace` both follow POSIX replace semantics. `os.rename` on Windows fails instead, which is inconsistent.

Always check target existence with a case-insensitive lookup immediately before renaming, and never use a bare replace. The check runs against the **live directory listing**, refreshed after every rename in that directory — earlier operations in the same run have already moved things, and files created by users during the run are invisible to any cached state (§9.2).

### 8.3 Collision resolution determinism

Two constraints, both required:

1. **Fixed processing order.** Sort each directory listing by byte order of the NFC name before resolving collisions (§7.3). `readdir` order is not stable across filesystems, so without this the choice of which file gets the suffix varies by platform.
2. **Deterministic suffix.** With the ordering fixed, a simple counter (`_1`, `_2`) is deterministic and readable. Without it, the suffix must derive from the source path (truncated hash). Prefer the counter plus explicit ordering.

Suffix insertion goes before the extension: `Bilancio_1.xlsx`, not `Bilancio.xlsx_1`. Re-validate the suffixed name against the length limits — the suffix can push a name over `LEN-003`.

A target name that cannot be made compliant after suffixing is `action = manual`, never a truncation. Shortening a document name is a judgment call the tool is not entitled to make on the user's behalf.

### 8.4 Locked files

- **Windows**: an open file yields a sharing violation. Office keeps `~$` lock files; OnlyOffice/LibreOffice keep `.~lock.*#`. Detect the lock file, skip the target, report it as `action = failed`, `outcome = error` — do not retry in a loop.
- **macOS/Linux**: `rename()` succeeds on open files. The application may then write to the old inode. Same policy: check for lock files and skip.

### 8.5 NextCloud-managed trees

Renaming directly on the server filesystem bypasses the database. Clients see delete + create: they re-download the file, and share links, comments, versions and tags are lost.

Two acceptable paths:

| Method | Preserves | Notes |
|---|---|---|
| WebDAV `MOVE` against the server | fileid, shares, versions, comments | **preferred**; rate-limit and handle 423 Locked |
| Filesystem rename + `occ files:scan --path` | nothing beyond file content | acceptable only for trees not yet shared |

Decide this before writing `auto-rename` — it changes the transport, not just a flag.

---

## 9. Execution model of `auto-rename`

There is no plan file and no remembered state. `auto-rename` walks the tree and **renames as it descends**, directory by directory, deciding each target from the filesystem as it is at that instant.

This is a deliberate consequence of dropping the plan/apply split. A persisted plan was always a liability — the interval between planning and applying is unbounded, users modify the tree in between, and applying remembered decisions to a changed tree is exactly how a rename overwrites a file nobody planned to touch. Deciding and acting in the same pass removes the class of bug rather than mitigating it. What remains is the TOCTOU window of §9.2, which is narrow and detectable.

The review use case the plan served is now `scan`: run it, read the report, then run `auto-rename`. The two runs are independent walks, and `auto-rename` re-derives everything — a `scan` report is a document for humans, never an input.

### 9.1 Per-directory cycle

Process **one directory at a time**, completing it before descending:

```
1. list        readdir + sort by byte order of NFC name (§7.3)
2. exclude     drop bookkeeping entries, --exclude and --exclude-regex matches (§2.3)
3. validate    rules → []Violation, per entry
4. resolve     planner → target names, collisions resolved within this listing (§8.3)
5. rename      per entry: check target free (§8.2), rename, journal
6. verify      re-read the directory, confirm each rename (§9.3)
7. descend     into the subdirectories, under their new names
```

Renaming a directory before descending into it — rather than after — is what keeps the recorded paths valid: children are then discovered and reported under the final parent name, and no path recorded earlier in the run goes stale. The cost is that a failed directory rename must be handled before its subtree is walked; on failure, descend under the **old** name and report the subtree normally. A parent that could not be fixed does not exempt its children from being examined.

Within a single directory, files and subdirectories are resolved together: they share one namespace and one collision domain.

### 9.2 TOCTOU

The window between `readdir` of a directory and `rename` inside it cannot be closed. Narrow it and detect it:

- The per-directory cycle above is the primary mitigation: the window is one directory wide, not one tree wide. Never a global walk followed by a global rename pass.
- Re-`stat` each target immediately before the rename; on Linux and macOS prefer `renameat2(RENAME_NOREPLACE)` where available, which makes the check atomic.
- **The collision check MUST run against the live directory listing, never against a cached one.** The failure mode is silent and destructive:

```
t0  resolve:  Bilancio.xlsx  →  bilancio.xlsx        target free
t1  user creates bilancio.xlsx
t2  rename:   cached state still says the target is free
              rename overwrites the user's file (§8.2)
```

Checking only the entries the tool intends to rename does not catch this: the file that gets destroyed is one the tool never looked at.

- On drift, abort the **current directory**, report every entry in it as `action = failed` / `outcome = error`, and continue with the rest of the tree. Do not retry, and do not fall back to overwriting. One volatile directory is not a reason to abandon a run over a large tree — but it is a reason to leave that directory alone.

### 9.3 Verification by re-read

After each rename, **re-read from the filesystem** and confirm the result before recording `outcome = ok`. A successful return from `rename()` is not evidence: case-only renames are silently ignored on some filesystems (§8.1), NFC-normalising renames may be silently re-decomposed by an HFS+ client, and a network filesystem may acknowledge an operation it did not perform.

The check:

1. Re-list the directory (a fresh `readdir`, not a `stat` of the expected name — `stat("bilancio.xlsx")` succeeds on a case-insensitive filesystem even when the file is still `Bilancio.xlsx`).
2. Confirm the target name is present **byte-for-byte** as intended, comparing NFC forms.
3. Confirm the source name is gone.
4. Re-validate the new name against `rules`. A rename that produced a still-non-compliant name is a bug in the planner, and the report must show it rather than hide it.

Any failure among these is `outcome = error` with the specific reason in `outcome_detail`. Never re-attempt the rename automatically: if the filesystem did not do what it reported, a second identical call is not more likely to work, and the tool no longer knows what state it is in.

Re-reading the whole directory once after finishing all its renames is acceptable and cheaper than one re-read per entry, provided the per-entry conclusions are drawn from that listing.

### 9.4 Other requirements

- **Idempotent** — a second `auto-rename` over a tree the first one fixed performs no renames and reports every entry as compliant. This is the strongest end-to-end test available; run it in CI over a fixture tree.
- **Resumable** — append to a journal after each successful rename; on restart, recover orphaned `*.safepath-*` temporaries (§8.1). The journal is a recovery aid and an audit trail, not an input to the next run: `auto-rename` always re-derives from the filesystem.
- **Non-fatal errors** — a locked file, an unreadable directory or a failed rename is reported and the run continues. Only an error that makes further work meaningless (unreadable scan root, output file not writable) aborts the run.
- **Quiescence** — on a NextCloud-managed tree, run during a window with sync paused. Renaming under active sync produces conflict copies of the files being renamed.

Archive the report and the journal together: they document what the run intended and what it actually did.

Archive the plan and the journal together: they document what the migration intended and what it actually did.

---

## 10. Cross-implementation parity

The two implementations are a liability unless parity is enforced mechanically.

- A single `testvectors.json` in the repo, consumed by both test suites. Neither implementation carries its own copy.
- CI matrix: {Go, Python} × {windows, macos, ubuntu} = 6 jobs, each producing a report from the same fixture manifest.
- A final job diffs all six outputs byte-for-byte. Any difference fails the build. **Both `--output-csv` and `--output-json` are diffed** — a format that is not compared is a format that will drift.
- The console table is compared too, with `NO_COLOR` set and a pinned terminal width, so that column elision is reproducible (§4.1).
- Include in the fixtures: NFD names, non-UTF-8 bytes, names at exactly the length limits, case-only pairs, reserved device names with dots, paths over `MAX_PATH`.
- Include a `--show-ok` run and a `--show-excluded` run: both change which rows are emitted, and both are easy to get subtly wrong in one implementation only.
- Include a run mixing several `--exclude` and `--exclude-regex` patterns, given in interleaved order, and assert that `excluded_by` names the same pattern in both implementations. Regex engine differences and first-match ordering are exactly where Go and Python drift apart quietly. Add a fixture pattern using a construct RE2 rejects, and assert **both** implementations exit 2 (§2.3).
- Include a multi-root invocation, to pin the root-ordering rule of §2.1.
- Both implementations emit the same `schema_version`, `unicode_version` and `ruleset_version` in the report header.
- For `auto-rename`, parity is checked on a **fixture tree copied into a temporary directory per job**, comparing the resulting reports and the resulting trees. Run it twice in each job: the second run must report no renames and exit 0 (idempotence, §9.4).

Treat the Python version as the reference for readability and the Go version as the reference for distribution — but neither is authoritative on behaviour. `testvectors.json` is.

---

## 11. Build and distribution

### Go

```
CGO_ENABLED=0    # fully static, no glibc/musl dependency
GOOS/GOARCH cross-compilation from a single build host
```

Single self-contained binary, ~8 MB, no runtime or installer on the client.

| Platform | Friction | Mitigation |
|---|---|---|
| Windows | SmartScreen warns on unsigned downloaded binaries | code-signing certificate, or distribute over an internal share (SmartScreen does not trigger) |
| macOS | Gatekeeper quarantines downloaded binaries | Apple notarization (Developer ID required), or document `xattr -d com.apple.quarantine` |
| Linux | none with `CGO_ENABLED=0` | — |

### Python

- Pin the interpreter minor version alongside `unicodedata2`; the pair defines behaviour.
- PyInstaller for client distribution faces the same signing and notarization issues as Go.
- Do not rely on `sys.getfilesystemencoding()`; handle bytes explicitly per §7.1.

---

## 12. Exit codes

| Code | `scan` | `auto-rename` |
|---|---|---|
| 0 | run completed, no violations | run completed, nothing left to fix |
| 1 | run completed, violations found | violations remained: `manual` or `failed` rows present |
| 2 | invalid arguments, unreadable configuration, or an unusable path argument | idem |
| 3 | I/O error during the walk or while writing an output file | idem, including a failed rename that is not attributable to a single entry |
| 4 | — | drift detected: a directory changed under the tool mid-run (§9.2) |

Violations are data, not errors — exit 1 must remain distinguishable from a crash so the tool can be scripted.

The asymmetry on exit 1 is deliberate. `scan` reports what is wrong, so any violation is exit 1. `auto-rename` is expected to fix what it finds, so **a run that repaired every violation exits 0**: the useful question for a script is not "was anything wrong?" but "is anything still wrong?". A violation that was found and corrected is a success, and the report still records it (§3.2).

Exit 4 outranks exit 1: drift means the tool cannot vouch for what it did, which matters more than the count of remaining violations. Entries excluded by `--exclude` never affect the exit code (§2.3).

---

## 13. Accepted non-determinism

Documented deliberately; do not attempt to fix.

- **mtime and size** in the manifest differ between hosts and are excluded from the report diff.
- **Names created by HFS+ clients in NFD** can appear between a scan and the next; they are detected as `CHR-002`, not prevented.
- **Symlink and cross-device entries** are reported as skipped, and the skip list depends on how the tree is mounted on the scanning host.
- **The TOCTOU window** between listing a directory and renaming inside it cannot be closed, only narrowed and detected (§9.2). A report describes the tree as it was during the walk, not as it is when the report is read.
