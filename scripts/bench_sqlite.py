#!/usr/bin/env python3
"""Benchmark clangd on a real, large single file: the SQLite amalgamation.

Downloads sqlite3.c (~270k lines) once, opens it in clangd, and times:

    * the first parse (didOpen -> first diagnostics)
    * a definition jump on sqlite3VdbeExec
    * a reference search on sqlite3VdbeExec, and how it compares to grep

    python3 scripts/bench_sqlite.py
"""

from __future__ import annotations

import io
import sys
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lsp_client import LspClient, fmt_location  # noqa: E402

AMALGAMATION_URL = "https://www.sqlite.org/2024/sqlite-amalgamation-3460100.zip"
SYMBOL = "sqlite3VdbeExec"


def ensure_amalgamation(workdir: Path) -> Path:
    target = workdir / "sqlite3.c"
    if target.exists():
        return target
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"downloading {AMALGAMATION_URL} ...")
    data = urllib.request.urlopen(AMALGAMATION_URL).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith("sqlite3.c"):
                target.write_bytes(z.read(name))
            if name.endswith("sqlite3.h"):
                (workdir / "sqlite3.h").write_bytes(z.read(name))
    (workdir / "compile_flags.txt").write_text("-std=c11\n-I.\n")
    return target


def first_def_line(path: Path, symbol: str) -> int:
    """Find a line where the symbol is *called*, to query its definition from."""
    for i, ln in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        if f"{symbol}(" in ln and not ln.lstrip().startswith(("/*", "*", "//")):
            return i
    raise SystemExit("symbol not found")


def main() -> None:
    workdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/sqlite-bench")
    src = ensure_amalgamation(workdir)
    lines = len(src.read_text(errors="replace").splitlines())
    size_mb = src.stat().st_size / 1e6
    print(f"\nsqlite3.c: {lines:,} lines / {size_mb:.1f} MB\n")

    client = LspClient(str(workdir), clangd="clangd")
    client.initialize()

    t0 = time.perf_counter()
    client.did_open(str(src))
    parse_ms = client.wait_for_diagnostics(str(src), timeout=120.0) * 1000.0
    print(f"[parse]       didOpen -> first diagnostics : {parse_ms/1000:.2f} s")

    call_line = first_def_line(src, SYMBOL)
    col = src.read_text(errors="replace").splitlines()[call_line - 1].find(SYMBOL)

    t = time.perf_counter()
    defs = client.definition(str(src), call_line - 1, col)
    def_ms = (time.perf_counter() - t) * 1000.0
    loc = fmt_location(defs[0], str(workdir)) if defs else "(none)"
    print(f"[definition]  {SYMBOL} call -> def   : {def_ms:.0f} ms  -> {loc}")

    t = time.perf_counter()
    refs = client.references(str(src), call_line - 1, col)
    ref_ms = (time.perf_counter() - t) * 1000.0
    print(f"[references]  {SYMBOL}              : {ref_ms:.0f} ms  -> {len(refs)} hits")

    grep = subprocess.run(
        ["grep", "-n", SYMBOL, "sqlite3.c"], cwd=workdir, capture_output=True, text=True
    )
    grep_hits = len([l for l in grep.stdout.splitlines() if l.strip()])
    print(f"[grep]        {SYMBOL}              :         {grep_hits} hits (includes comments)")

    client.shutdown()


if __name__ == "__main__":
    main()
