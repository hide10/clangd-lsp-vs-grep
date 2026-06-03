#!/usr/bin/env python3
"""Ask clangd the same questions you'd otherwise grep for, and time the answers.

Examples
--------
Reproduce the article's grep-vs-LSP comparison on the bundled demo project:

    python3 scripts/lsp_probe.py demo demo-project

Ad-hoc queries against any project that has a compile_flags.txt or
compile_commands.json at its root:

    python3 scripts/lsp_probe.py def   path/to/proj src/foo.c 42 11
    python3 scripts/lsp_probe.py refs  path/to/proj src/foo.c 42 11
    python3 scripts/lsp_probe.py rename path/to/proj src/foo.c 42 11 new_name
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lsp_client import LspClient, find_column, fmt_location, uri_to_path  # noqa: E402

CLANGD = "clangd"


def grep_count(root: str, term: str) -> int:
    res = subprocess.run(
        ["grep", "-rn", term, "--include=*.c", "--include=*.h", "."],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return len([ln for ln in res.stdout.splitlines() if ln.strip()])


def open_all(client: LspClient, root: str) -> None:
    for c in sorted(Path(root).glob("*.c")):
        client.did_open(str(c))
    for h in sorted(Path(root).glob("*.h")):
        client.did_open(str(h), language_id="c")


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - start) * 1000.0


def cmd_demo(root: str) -> None:
    root = str(Path(root).resolve())
    client = LspClient(root, clangd=CLANGD)
    client.initialize()
    open_all(client, root)
    # Let clangd settle on the main translation units.
    client.wait_for_diagnostics(str(Path(root) / "main.c"))
    client.wait_for_diagnostics(str(Path(root) / "worker.c"))

    questions = [
        ("main.c's init_session() call -> definition", "main.c", "init_session", "def"),
        ("worker.c's init_session() call -> definition", "worker.c", "init_session", "def"),
        ("handle_session() definition (built by a macro)", "main.c", "handle_session", "def"),
    ]

    print(f"\nproject: {root}\n")
    header = f"{'question':<46} {'grep':>10} {'clangd (LSP)':>22} {'time':>8}"
    print(header)
    print("-" * len(header))
    for desc, fname, symbol, _ in questions:
        path = str(Path(root) / fname)
        line = _line_with(path, symbol)
        col = find_column(path, line, symbol)
        locs, ms = timed(lambda: client.definition(path, line - 1, col))
        grep_hits = grep_count(root, symbol)
        answer = fmt_location(locs[0], root) if locs else "(none)"
        print(f"{desc:<46} {str(grep_hits)+' hits':>10} {answer:>22} {ms:6.1f} ms")

    # Rename demo: Connection::fd -> socket_fd
    print("\nrename Connection::fd -> socket_fd")
    sc = str(Path(root) / "session.c")
    line = _line_with(sc, "conn->fd")
    col = find_column(sc, line, "fd") if "fd" in Path(sc).read_text() else 0
    # point exactly at the 'fd' member access
    col = Path(sc).read_text().splitlines()[line - 1].find("->fd") + 2
    edit, ms = timed(lambda: client.rename(sc, line - 1, col, "socket_fd"))
    changes = edit.get("changes") or {}
    if not changes and "documentChanges" in edit:
        changes = {dc["textDocument"]["uri"]: dc["edits"] for dc in edit["documentChanges"]}
    total = sum(len(v) for v in changes.values())
    print(f"  {total} edits across {len(changes)} files   ({ms:.1f} ms)")
    for uri in sorted(changes):
        rel = Path(uri_to_path(uri)).relative_to(root)
        spots = ", ".join(
            f"{e['range']['start']['line']+1}:{e['range']['start']['character']+1}"
            for e in changes[uri]
        )
        print(f"    {str(rel):<12} {spots}")

    client.shutdown()


def _line_with(path: str, symbol: str) -> int:
    for i, ln in enumerate(Path(path).read_text().splitlines(), start=1):
        if symbol in ln and not ln.lstrip().startswith(("/*", "*", "//")):
            return i
    # fall back to any line (e.g. for a call that's the only occurrence)
    for i, ln in enumerate(Path(path).read_text().splitlines(), start=1):
        if symbol in ln:
            return i
    raise SystemExit(f"symbol {symbol!r} not found in {path}")


def _generic(kind: str, args: list[str]) -> None:
    root, file, line, col = args[0], args[1], int(args[2]), int(args[3])
    client = LspClient(str(Path(root).resolve()), clangd=CLANGD)
    client.initialize()
    open_all(client, str(Path(root).resolve()))
    client.wait_for_diagnostics(str(Path(root).resolve() / Path(file).name))
    path = str(Path(root).resolve() / file)
    if kind == "def":
        locs, ms = timed(lambda: client.definition(path, line - 1, col - 1))
        for l in locs:
            print(fmt_location(l, str(Path(root).resolve())))
        print(f"({ms:.1f} ms)")
    elif kind == "refs":
        locs, ms = timed(lambda: client.references(path, line - 1, col - 1))
        for l in locs:
            print(fmt_location(l, str(Path(root).resolve())))
        print(f"{len(locs)} refs ({ms:.1f} ms)")
    elif kind == "rename":
        new = args[4]
        edit, ms = timed(lambda: client.rename(path, line - 1, col - 1, new))
        print(edit)
        print(f"({ms:.1f} ms)")
    client.shutdown()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cmd = sys.argv[1]
    if cmd == "demo":
        cmd_demo(sys.argv[2] if len(sys.argv) > 2 else "demo-project")
    elif cmd in ("def", "refs", "rename"):
        _generic(cmd, sys.argv[2:])
    else:
        print(__doc__)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
