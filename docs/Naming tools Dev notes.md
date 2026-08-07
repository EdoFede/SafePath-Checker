# Naming Tools — Development Notes

Implementation hazards for the compliance checker and the renamer, targeting **Windows / macOS / Linux** with byte-identical results across both platforms and both implementations (**Go** and **Python**).

Naming rules themselves are out of scope here — see `file-naming-rules.md`.

---

## 1. Architecture

**One binary, three subcommands.** No mandatory intermediate file.

```
areanaming check <root>          walk + validate            ──► report.jsonl
areanaming plan  <root>          walk + validate + resolve  ──► plan.jsonl
areanaming apply <plan>          re-walk + verify + rename  ──► journal.jsonl
```

The separation that matters is **internal**, not between processes:

```
package walker   filesystem traversal, OS-specific   ──► []Entry
package rules    validation, no filesystem access    ──► []Violation
package planner  rename resolution                   ──► []Operation
```

`rules` never touches the filesystem. All OS divergence is confined to `walker`. The test suite injects synthetic `Entry` values directly, so identical cross-platform results are a property of the design rather than of the workflow.

The **manifest** — a JSONL serialisation of `[]Entry` — is an optional output (`--emit-manifest`), not a required step. It is worth producing for two purposes: archiving the state a report refers to, and diffing consecutive runs to see what changed in the tree. It is also the transport used by the cross-implementation parity tests (§7).

---

## 2. Determinism contract

Anything below that differs between two runs is a bug.

| Aspect | Rule |
|---|---|
| Path separator in manifest | always `/`, never `\` |
| Path form in manifest | NFC, relative to sync root, no leading `./` |
| Sort order | byte order of the UTF-8 NFC path. In Go, plain `<` on `string`; in Python, plain `<` on `str` — codepoint order and UTF-8 byte order coincide, so both agree |
| Locale | never used. No `strings.ToLower` with locale, no `locale.strcoll`, no `time.Local` |
| Timestamps | UTC, RFC 3339, only in metadata fields — never in identifiers or suffixes |
| JSON output | UTF-8 without BOM, `\n` line endings, sorted keys, one object per line |
| Map/dict iteration | never emitted directly — Go randomizes map order by design; always sort first |
| Floating point | not used anywhere |

Write the manifest and all outputs in binary mode to avoid Windows CRLF translation.

---

## 3. Unicode

### 3.1 Table pinning

Both implementations MUST declare the Unicode version they were built against, and the version MUST appear in the report header. Two runs with different tables are not comparable.

| | Go | Python |
|---|---|---|
| Normalization | `golang.org/x/text/unicode/norm` | `unicodedata2` (**not** stdlib `unicodedata`) |
| Case folding | `golang.org/x/text/cases.Fold()` | `str.casefold()` |
| Version pinning | `go.mod` pins `x/text` | `requirements.txt` pins `unicodedata2` |

Stdlib `unicodedata` is bound to the CPython build: 3.11 and 3.13 ship different tables. `unicodedata2` decouples them and is the only way to match a pinned Go build.

Normalization of already-assigned characters is stable across Unicode versions by policy; **category lookups and case folding are not**. The risk surface is `unicodedata.category()` (used for the combining-mark check) and folding, not NFC itself.

### 3.2 Case folding, not lowercasing

`strings.ToLower` (Go) and `str.lower()` (Python) are **not** equivalent to full case folding and MUST NOT be used for the collision key.

```
ß      →  lower: ß      fold: ss
ﬁ      →  lower: ﬁ      fold: fi
İ      →  lower: i̇      fold: i̇
K (U+212A) → lower: k   fold: k
```

Profile B rejects most of these as `CHR-001`, but the collision check runs on the **pre-remediation dataset**, which contains arbitrary legacy names. Full folding is required there.

Collision key: `casefold(NFC(name))`. Compare within a single directory only.

### 3.3 NFC vs NFD

- Manifest stores NFC.
- Length checks are computed on NFD (worst case) — see the rules document.
- The walker MUST record whether the on-disk name was already NFC. Converting silently would hide `CHR-002` findings, which are exactly the macOS/HFS+ artifacts the audit exists to detect.

Suggested manifest fields: `path` (NFC) plus `nfc_normalized: true|false`.

---

## 4. Path handling

### 4.1 Non-UTF-8 names (Linux)

Linux filenames are byte strings with no encoding guarantee. Both languages surface this differently:

- **Go**: `string` holds arbitrary bytes; invalid sequences survive but JSON encoding will replace them with U+FFFD.
- **Python**: `os.scandir()` returns `str` with `surrogateescape`; lone surrogates cannot be serialised to JSON.

Neither is representable in JSON. Add a fallback field:

```json
{"path": "<lossy UTF-8 rendering>", "path_b64": "<raw bytes, base64>", "valid_utf8": false}
```

When `valid_utf8` is false, the checker emits `CHR-001` without further analysis, and the renamer treats the entry as manual-intervention-only.

### 4.2 Windows long paths

Even with the 180-char budget, the walker may traverse pre-remediation trees that exceed `MAX_PATH`.

- Go applies the `\\?\` prefix automatically for absolute paths in the `os` package.
- Python needs `LongPathsEnabled=1` **and** a manifest-aware interpreter, or an explicit `\\?\` prefix.

The `\\?\` form requires backslashes, an absolute path, and no `.` or `..` components — normalise before prefixing. Verify long-path behaviour explicitly in the test suite; it is the most common source of Go/Python divergence on Windows.

macOS `PATH_MAX` is 1024 bytes and cannot be lifted — it becomes the binding constraint once Windows long paths are enabled.

### 4.3 Traversal

- **Do not follow symlinks, junctions or reparse points.** Record and skip. Following them breaks depth counting and can loop.
- **Do not cross filesystem boundaries.** Compare device IDs; on Windows use the volume serial number.
- Depth is counted relative to the sync root, not to the filesystem root.
- Skip client and server bookkeeping: `.nextcloud`, `.sync_*.db`, `.owncloudsync.log*`, `.~lock.*`, `~$*`, `*.part`, `*.filepart`, `files_versions/`, `files_trashbin/`.
- Enumeration order from `readdir` differs across ext4, NTFS and APFS. **Sort every directory listing** before emitting to the manifest.

---

## 5. Rename hazards

### 5.1 Case-only rename

`Bilancio.xlsx` → `bilancio.xlsx` on NTFS, APFS or HFS+ is either rejected, silently ignored, or succeeds depending on filesystem and OS version. Never rely on it.

Mandatory two-step:

```
Bilancio.xlsx  →  Bilancio.xlsx.arename-<hash>  →  bilancio.xlsx
```

Requirements on the temporary name:

- **Deterministic** — derived from a hash of the target path, so a crashed run can be resumed and the orphan recognised.
- Same directory (avoids `EXDEV`).
- Recognisable prefix, so a recovery pass can find and finish interrupted operations.
- Verify the temp name does not itself exist before use.

The apply step must be crash-tolerant: on startup, scan for orphaned `*.arename-*` entries and either complete or roll back.

### 5.2 Case-insensitive collisions during apply

On a case-insensitive filesystem, renaming `A.txt` to `b.txt` when `B.txt` exists **overwrites silently** — Go's `os.Rename` and Python's `os.replace` both follow POSIX replace semantics. `os.rename` on Windows fails instead, which is inconsistent.

Always check target existence with a case-insensitive lookup immediately before renaming, and never use a bare replace. The check runs against the **live directory listing**, refreshed after every rename in that directory — earlier operations in the same run have already moved things, and files created by users since planning are invisible to any cached state (§6.1).

### 5.3 Collision resolution determinism

Two constraints, both required:

1. **Fixed processing order.** Sort the manifest by byte order of the NFC path before resolving collisions. `readdir` order is not stable across filesystems, so without this the choice of which file gets the suffix varies by platform.
2. **Deterministic suffix.** With the ordering fixed, a simple counter (`_1`, `_2`) is deterministic and readable. Without it, the suffix must derive from the source path (truncated hash). Prefer the counter plus explicit ordering.

Suffix insertion goes before the extension: `Bilancio_1.xlsx`, not `Bilancio.xlsx_1`. Re-validate the suffixed name against the length limits — the suffix can push a name over `LEN-003`.

### 5.4 Locked files

- **Windows**: an open file yields a sharing violation. Office keeps `~$` lock files; OnlyOffice/LibreOffice keep `.~lock.*#`. Detect the lock file, skip the target, report it — do not retry in a loop.
- **macOS/Linux**: `rename()` succeeds on open files. The application may then write to the old inode. Same policy: check for lock files and skip.

### 5.5 NextCloud-managed trees

Renaming directly on the server filesystem bypasses the database. Clients see delete + create: they re-download the file, and share links, comments, versions and tags are lost.

Two acceptable paths:

| Method | Preserves | Notes |
|---|---|---|
| WebDAV `MOVE` against the server | fileid, shares, versions, comments | **preferred**; rate-limit and handle 423 Locked |
| Filesystem rename + `occ files:scan --path` | nothing beyond file content | acceptable only for trees not yet shared |

Decide this before writing the apply step — it changes the transport, not just a flag.

---

## 6. Plan / apply model

`plan` and `apply` **both perform a fresh filesystem walk**. A plan is never applied against remembered state: users modify the tree between runs, and the interval between planning and applying is unbounded.

The plan exists for one reason only — letting a human review the rename mapping before a destructive operation on a large tree. It is a review artifact, not a source of truth about the filesystem.

```json
{"from":"...","to":"...","codes":["POS-002"],"action":"rename"}
{"from":"...","codes":["CHR-001"],"action":"manual","reason":"non-UTF-8 name"}
```

### 6.1 What `apply` must re-derive

Everything that depends on the state of the tree:

| Recomputed at apply time | Why |
|---|---|
| Directory listing of every touched directory | new files may have appeared since planning |
| Case-insensitive existence of every target | see §5.2 — the decisive check |
| Collision resolution and suffix assignment | a new file can join a collision group |
| Size and mtime of every source | detects modification since planning |

**The collision check MUST run against the live filesystem, never against plan-time state.** The failure mode is silent and destructive:

```
t0  plan:   Bilancio.xlsx  →  bilancio.xlsx
t1  user creates bilancio.xlsx
t2  apply:  source unchanged, plan-time state says target is free
            rename overwrites the user's file (§5.2)
```

Verifying only the sources named in the plan does not catch this, because the file that gets destroyed is not in the plan.

### 6.2 TOCTOU

The window between `readdir` of a directory and `rename` inside it cannot be closed. Narrow it and detect it:

- Process **one directory at a time**: list, resolve, rename, move on. Never a global scan followed by a global rename pass.
- Re-`stat` each target immediately before the rename; on Linux and macOS prefer `renameat2(RENAME_NOREPLACE)` where available, which makes the check atomic.
- On drift, abort the directory and report it. Do not retry, and do not fall back to overwriting.

### 6.3 Other apply requirements

- **Idempotent** — re-running a completed plan is a no-op.
- **Resumable** — append to a journal after each successful rename; on restart, skip journaled entries and recover orphaned `*.arename-*` temporaries (§5.1).
- **Deepest-first ordering** — rename files before their parent directories, or recorded paths go stale mid-run.
- **Dry-run by default** — `--apply` is opt-in.
- **Quiescence** — on a NextCloud-managed tree, run during a window with sync paused. Renaming under active sync produces conflict copies of the files being renamed.

Archive the plan and the journal together: they document what the migration intended and what it actually did.

---

## 7. Cross-implementation parity

The two implementations are a liability unless parity is enforced mechanically.

- A single `testvectors.json` in the repo, consumed by both test suites. Neither implementation carries its own copy.
- CI matrix: {Go, Python} × {windows, macos, ubuntu} = 6 jobs, each producing a report from the same fixture manifest.
- A final job diffs all six outputs byte-for-byte. Any difference fails the build.
- Include in the fixtures: NFD names, non-UTF-8 bytes, names at exactly the length limits, case-only pairs, reserved device names with dots, paths over `MAX_PATH`.
- Both implementations emit the same `schema_version`, `unicode_version` and `ruleset_version` in the report header.

Treat the Python version as the reference for readability and the Go version as the reference for distribution — but neither is authoritative on behaviour. `testvectors.json` is.

---

## 8. Build and distribution

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
- Do not rely on `sys.getfilesystemencoding()`; handle bytes explicitly per §4.1.

---

## 9. Exit codes

| Code | Meaning |
|---|---|
| 0 | run completed, no violations |
| 1 | run completed, violations found |
| 2 | invalid arguments or unreadable configuration |
| 3 | I/O error during scan or apply |
| 4 | drift detected at apply time (tree changed since planning) |

Violations are data, not errors — exit 1 must remain distinguishable from a crash so the tool can be scripted.

---

## 10. Accepted non-determinism

Documented deliberately; do not attempt to fix.

- **mtime and size** in the manifest differ between hosts and are excluded from the report diff.
- **Names created by HFS+ clients in NFD** can appear between a scan and the next; they are detected as `CHR-002`, not prevented.
- **Symlink and cross-device entries** are reported as skipped, and the skip list depends on how the tree is mounted on the scanning host.
- **The TOCTOU window** between listing a directory and renaming inside it cannot be closed, only narrowed and detected (§6.2). A report describes the tree as it was during the walk, not as it is when the report is read.
