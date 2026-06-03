"""A tiny synchronous LSP client for clangd.

No dependencies beyond the Python standard library. It speaks just enough of
the Language Server Protocol to ask clangd three questions:

    * where is the definition of the symbol under this cursor?  (textDocument/definition)
    * where are all the references?                              (textDocument/references)
    * rename this symbol                                         (textDocument/rename)

clangd talks JSON-RPC over stdio, with each message prefixed by a
``Content-Length:`` header. That framing is the only "protocol" code here.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional


def path_to_uri(path: str) -> str:
    return Path(path).resolve().as_uri()


def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(uri).path)
    return uri


class LspClient:
    def __init__(self, root: str, clangd: str = "clangd", background_index: bool = False,
                 extra_args: Optional[list[str]] = None):
        self.root = str(Path(root).resolve())
        # Background indexing lets cross-file queries (references / rename) span
        # the whole project, not just the files you've opened. Off by default so
        # the demo is instant; the MCP bridge turns it on.
        args = [clangd, f"--background-index={'true' if background_index else 'false'}",
                "--log=error"]
        if extra_args:
            args.extend(extra_args)
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._id = 0
        self._responses: dict[int, Any] = {}
        self._notifications: list[dict] = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ---- framing -------------------------------------------------------
    def _send(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        assert self.proc.stdin is not None
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def _read_loop(self) -> None:
        out = self.proc.stdout
        assert out is not None
        while True:
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = out.read(1)
                if not chunk:
                    return
                header += chunk
            length = 0
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1].strip())
            body = b""
            while len(body) < length:
                chunk = out.read(length - len(body))
                if not chunk:
                    return
                body += chunk
            msg = json.loads(body.decode("utf-8"))
            with self._lock:
                if "id" in msg and ("result" in msg or "error" in msg):
                    self._responses[msg["id"]] = msg
                else:
                    self._notifications.append(msg)

    # ---- requests ------------------------------------------------------
    def _request(self, method: str, params: dict, timeout: float = 20.0) -> Any:
        with self._lock:
            self._id += 1
            rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self._responses:
                    msg = self._responses.pop(rid)
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg["result"]
            time.sleep(0.002)
        raise TimeoutError(f"{method} timed out")

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- lifecycle -----------------------------------------------------
    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": path_to_uri(self.root),
                "capabilities": {
                    "textDocument": {
                        "definition": {"linkSupport": True},
                        "references": {},
                        "rename": {"prepareSupport": False},
                        "publishDiagnostics": {},
                    }
                },
            },
        )
        self._notify("initialized", {})

    def did_open(self, path: str, language_id: str = "c") -> None:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path_to_uri(path),
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )

    def wait_for_diagnostics(self, path: str, timeout: float = 30.0) -> float:
        """Block until clangd publishes diagnostics for ``path``.

        Returns how long the wait took (a proxy for "time to first parse").
        """
        uri = path_to_uri(path)
        start = time.time()
        deadline = start + timeout
        while time.time() < deadline:
            with self._lock:
                for n in self._notifications:
                    if n.get("method") == "textDocument/publishDiagnostics" \
                            and n.get("params", {}).get("uri") == uri:
                        return time.time() - start
            time.sleep(0.005)
        return time.time() - start

    # ---- queries -------------------------------------------------------
    def definition(self, path: str, line: int, character: int) -> list[dict]:
        result = self._request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line, "character": character},
            },
        )
        return _as_locations(result)

    def references(self, path: str, line: int, character: int, include_decl: bool = True) -> list[dict]:
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_decl},
            },
        )
        return _as_locations(result)

    def rename(self, path: str, line: int, character: int, new_name: str) -> dict:
        return self._request(
            "textDocument/rename",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line, "character": character},
                "newName": new_name,
            },
        )

    def shutdown(self) -> None:
        try:
            self._request("shutdown", {}, timeout=5.0)
            self._notify("exit", {})
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


def _as_locations(result: Any) -> list[dict]:
    """Normalize Location | Location[] | LocationLink[] into a flat list."""
    if result is None:
        return []
    if isinstance(result, dict):
        result = [result]
    out = []
    for item in result:
        if "targetUri" in item:  # LocationLink
            out.append({"uri": item["targetUri"], "range": item["targetSelectionRange"]})
        else:
            out.append({"uri": item["uri"], "range": item["range"]})
    return out


def find_column(path: str, line_1based: int, symbol: str) -> int:
    """Return the 0-based column of the first occurrence of ``symbol`` on a line."""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    line = lines[line_1based - 1]
    col = line.find(symbol)
    return col if col >= 0 else 0


def fmt_location(loc: dict, root: str) -> str:
    path = os.path.relpath(uri_to_path(loc["uri"]), root)
    line = loc["range"]["start"]["line"] + 1
    col = loc["range"]["start"]["character"] + 1
    return f"{path}:{line}:{col}"
