#!/usr/bin/env python3
"""clangd-lsp-bridge: a minimal MCP server that exposes clangd to Claude Code.

It hands Claude Code three tools — lsp_definition, lsp_references, lsp_rename —
and answers each by forwarding the question to a clangd process over LSP. Only
the Python standard library is used.

Register it with Claude Code:

    claude mcp add clangd-lsp --scope user -- \\
        python3 /abs/path/scripts/lsp_mcp_server.py /abs/path/to/your/project

Then `claude mcp list` should show:  clangd-lsp: ... - ✓ Connected
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lsp_client import LspClient, fmt_location, find_column, uri_to_path  # noqa: E402

SERVER_NAME = "clangd-lsp-bridge"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "lsp_definition",
        "description": "Jump to the definition of the symbol at a position. Resolves "
        "overloads, file-local statics, and macro-generated names that grep cannot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Path relative to the project root."},
                "line": {"type": "integer", "description": "1-based line number."},
                "symbol": {"type": "string", "description": "Symbol name on that line (used to find the column)."},
                "column": {"type": "integer", "description": "1-based column. Optional if 'symbol' is given."},
            },
            "required": ["file", "line"],
        },
    },
    {
        "name": "lsp_references",
        "description": "List every reference to the symbol at a position, excluding "
        "comments and unrelated same-name symbols.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "line": {"type": "integer"},
                "symbol": {"type": "string"},
                "column": {"type": "integer"},
            },
            "required": ["file", "line"],
        },
    },
    {
        "name": "lsp_rename",
        "description": "Rename the symbol at a position across the whole project, "
        "touching only real references (never strings or comments). Returns the edits "
        "without applying them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "line": {"type": "integer"},
                "symbol": {"type": "string"},
                "column": {"type": "integer"},
                "new_name": {"type": "string"},
            },
            "required": ["file", "line", "new_name"],
        },
    },
]


class Bridge:
    def __init__(self, root: str):
        self.root = str(Path(root).resolve())
        self.client: LspClient | None = None
        self._opened: set[str] = set()

    # Open at most this many source files so cross-file rename/references work.
    # Background indexing covers anything beyond the cap on large repos.
    MAX_OPEN = 2000

    def _ensure(self) -> LspClient:
        if self.client is None:
            self.client = LspClient(self.root, clangd="clangd", background_index=True)
            self.client.initialize()
            self._open_project()
        return self.client

    def _open_project(self) -> None:
        assert self.client is not None
        exts = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx")
        count = 0
        for p in sorted(Path(self.root).rglob("*")):
            if count >= self.MAX_OPEN:
                break
            if p.suffix.lower() in exts and p.is_file():
                lang = "cpp" if p.suffix.lower() in (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx") else "c"
                self.client.did_open(str(p), language_id=lang)
                self._opened.add(str(p))
                count += 1

    def _open(self, path: str) -> None:
        c = self._ensure()
        if path not in self._opened:
            lang = "cpp" if path.endswith((".cpp", ".cc", ".hpp", ".hh")) else "c"
            c.did_open(path, language_id=lang)
            self._opened.add(path)

    def _resolve_pos(self, args: dict) -> tuple[str, int, int]:
        path = str(Path(self.root) / args["file"])
        self._open(path)
        # Block until clangd has parsed the target file (returns immediately if
        # diagnostics were already published).
        self._ensure().wait_for_diagnostics(path, timeout=30.0)
        line = int(args["line"])
        if "column" in args and args["column"]:
            col = int(args["column"]) - 1
        elif "symbol" in args and args["symbol"]:
            col = find_column(path, line, args["symbol"])
        else:
            col = 0
        return path, line - 1, col

    def definition(self, args: dict) -> str:
        path, line, col = self._resolve_pos(args)
        locs = self._ensure().definition(path, line, col)
        if not locs:
            return "no definition found"
        return "\n".join(fmt_location(l, self.root) for l in locs)

    def references(self, args: dict) -> str:
        path, line, col = self._resolve_pos(args)
        locs = self._ensure().references(path, line, col)
        if not locs:
            return "no references found"
        return f"{len(locs)} references:\n" + "\n".join(fmt_location(l, self.root) for l in locs)

    def rename(self, args: dict) -> str:
        path, line, col = self._resolve_pos(args)
        edit = self._ensure().rename(path, line, col, args["new_name"])
        changes = edit.get("changes") or {}
        if not changes and "documentChanges" in edit:
            changes = {dc["textDocument"]["uri"]: dc["edits"] for dc in edit["documentChanges"]}
        total = sum(len(v) for v in changes.values())
        lines = [f"{total} edits across {len(changes)} files:"]
        for uri in sorted(changes):
            import os
            rel = os.path.relpath(uri_to_path(uri), self.root)
            spots = ", ".join(
                f"{e['range']['start']['line']+1}:{e['range']['start']['character']+1}"
                for e in changes[uri]
            )
            lines.append(f"  {rel}: {spots}")
        return "\n".join(lines)


# ---- MCP stdio plumbing (Content-Length framed JSON-RPC) ----------------
def read_message():
    header = b""
    while b"\r\n\r\n" not in header:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        header += ch
    length = 0
    for line in header.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1].strip())
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(msg: dict) -> None:
    body = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: lsp_mcp_server.py <project-root>\n")
        raise SystemExit(2)
    bridge = Bridge(sys.argv[1])
    handlers = {
        "lsp_definition": bridge.definition,
        "lsp_references": bridge.references,
        "lsp_rename": bridge.rename,
    }

    while True:
        msg = read_message()
        if msg is None:
            break
        method = msg.get("method")
        mid = msg.get("id")

        if method == "initialize":
            write_message({
                "jsonrpc": "2.0", "id": mid,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            write_message({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            try:
                text = handlers[name](args)
                write_message({
                    "jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": text}]},
                })
            except Exception as exc:  # surface tool errors to the model
                write_message({
                    "jsonrpc": "2.0", "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": f"error: {exc}"}],
                        "isError": True,
                    },
                })
        elif mid is not None:
            write_message({
                "jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            })

    if bridge.client:
        bridge.client.shutdown()


if __name__ == "__main__":
    main()
