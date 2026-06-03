# clangd-lsp-vs-grep

A small, self-contained kit for reproducing **"grep vs. LSP (clangd)"** on your
own machine, and for wiring clangd into **Claude Code** through a minimal MCP
server.

It backs this article (Japanese): **[Claude Codeにclangdを繋いでみた — grep探索とLSPの精度・速度を実測で比べる](https://www.hide10.com/post/claude-code-clangd-lsp-mcp-2026/)**

Everything here uses the **Python standard library only** (plus `clangd`
itself, which `scripts/install-clangd.sh` fetches without root).

---

## TL;DR

```bash
git clone https://github.com/hide10/clangd-lsp-vs-grep
cd clangd-lsp-vs-grep
bash run-demo.sh         # installs clangd if missing, then runs the comparison
```

Expected output (timings vary by machine):

```
project: .../demo-project

question                                             grep           clangd (LSP)     time
-----------------------------------------------------------------------------------------
main.c's init_session() call -> definition        10 hits          session.c:5:5    4.3 ms
worker.c's init_session() call -> definition      10 hits          worker.c:5:12    4.3 ms
handle_session() definition (built by a macro)     4 hits         handlers.c:7:1    2.2 ms

rename Connection::fd -> socket_fd
  5 edits across 3 files   (2.2 ms)
    main.c       11:30
    session.c    6:11, 8:54, 9:18
    session.h    5:9
```

The point: grep returns a pile of hits it cannot tell apart (and **zero** for
the macro-built `handle_session`), while clangd lands on the one correct
definition every time — distinguishing the global `init_session` from the
file-local `static` one by call site, and finding a name that never appears
literally in the source.

---

## What's in here

```
demo-project/            A tiny C project with traps grep falls into
  session.c / session.h    the real, global init_session()
  worker.c                 a different, file-local `static` init_session()
  log.c                    init_session in comments and a printf string (noise)
  handlers.c / handlers.h  handle_session() assembled by a macro (DEFINE_HANDLER)
  main.c                   uses both
  compile_flags.txt        all clangd needs to analyze the project
  Makefile                 `make` to compile, `make compdb` for compile_commands.json

scripts/
  install-clangd.sh        download a standalone clangd into ~/.local/bin (no sudo)
  lsp_client.py            ~200 lines of LSP-over-stdio; the only "protocol" code
  lsp_probe.py             ask clangd the questions you'd otherwise grep for
  lsp_mcp_server.py        clangd-lsp-bridge: expose clangd to Claude Code over MCP
  bench_sqlite.py          run the same queries against 250k+ lines of sqlite3.c

run-demo.sh                install clangd (if needed) + run the demo
```

---

## The traps, explained

| Trap | What grep sees | What clangd sees |
|---|---|---|
| Two functions named `init_session` (one global, one file-local `static`) | identical text, indistinguishable | two different symbols; resolves by call-site scope |
| `init_session` in comments and a `printf` string | matches them as if they were code | ignores them |
| `handle_session` built by `DEFINE_HANDLER(session)` via `##` token-pasting | the literal name never appears → **0 definitions** | resolves it to the macro expansion |
| Renaming `Connection::fd` while a log message also contains "fd" | a blind replace corrupts the string | renames only the real field references |

The C compiles and runs (`cd demo-project && make && ./demo`), so the traps are
valid code, not contrived strings.

---

## Reproduce the large-file benchmark

```bash
python3 scripts/bench_sqlite.py
```

Downloads the SQLite amalgamation (one ~250k-line `sqlite3.c`) once and times
the first parse, a definition jump, and a reference search. On the author's
machine:

```
sqlite3.c: 257,679 lines / 9.1 MB

[parse]       didOpen -> first diagnostics : 1.30 s
[definition]  sqlite3VdbeExec call -> def   : 40 ms  -> sqlite3.c:93917:20
[references]  sqlite3VdbeExec              : 19 ms  -> 4 hits
[grep]        sqlite3VdbeExec              :         8 hits (includes comments)
```

Once the file is parsed, queries are tens of milliseconds regardless of file
size; grep returns 8 hits (half of them comments) where clangd returns the 4
real ones.

---

## Wire clangd into Claude Code (MCP)

`scripts/lsp_mcp_server.py` is a minimal MCP server (name `clangd-lsp-bridge`)
that gives Claude Code three tools — `lsp_definition`, `lsp_references`,
`lsp_rename` — each backed by clangd.

```bash
claude mcp add clangd-lsp --scope user -- \
    python3 "$PWD/scripts/lsp_mcp_server.py" "$PWD/demo-project"

claude mcp list
# clangd-lsp: python3 .../lsp_mcp_server.py ... - ✓ Connected
```

Point the last argument at your own project root instead of `demo-project`.
In production you'd usually adopt a maintained LSP-MCP bridge rather than this
one; it's here so you can see exactly how little stands between Claude Code and
clangd.

---

## Use it on your own (or your company's) codebase

1. Make clangd see your build: generate `compile_commands.json`.
   - CMake: `cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ...`
   - Make: `bear -- make`
   - Or, for trivial projects, a `compile_flags.txt` with your `-std`/`-I` flags.
2. Install clangd: `bash scripts/install-clangd.sh` (no root required).
3. Query directly to sanity-check:
   `python3 scripts/lsp_probe.py def /path/to/proj src/foo.c <line> <col>`
4. Register the MCP server pointed at your project root and let Claude Code use
   `lsp_definition` / `lsp_references` / `lsp_rename` instead of grep.

clangd handles C and C++. For other languages, swap the language server
(`rust-analyzer`, `typescript-language-server`, …) — the LSP requests are the
same.

---

## License

MIT. See [LICENSE](LICENSE).
