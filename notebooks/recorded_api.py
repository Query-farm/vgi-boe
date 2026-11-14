"""Serve verified official XML recordings to the unchanged worker over loopback."""

from __future__ import annotations

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit


class RecordedApi:
    def __init__(self, directory: Path, year: int):
        self.directory = directory
        self.manifest = json.loads((directory / "manifest.json").read_text())
        self.records = {key: r for key, r in self.manifest["records"].items() if key.startswith(f"{year}-")}
        self.payloads = {}
        for key, record in self.records.items():
            raw = (directory / record["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError(f"Recording checksum mismatch: {record['file']}")
            self.payloads[key] = raw
        if len(self.records) != 2:
            raise ValueError("Both the anchor and selected year must have recordings")
        self.requests = []
        self.server = None
        self.thread = None

    def start(self):
        replay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, keep_blank_values=True)
                match = next(
                    (
                        key
                        for key, record in replay.records.items()
                        if query == {k: [v] for k, v in record["request_query"].items()}
                    ),
                    None,
                )
                if parsed.path != "/_iadb-fromshowcolumns.asp" or match is None:
                    self.send_error(400, "This request is outside the documented recording coverage")
                    return
                raw = replay.payloads[match]
                replay.requests.append(match)
                self.send_response(200)
                self.send_header("Content-Type", replay.records[match]["content_type"])
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
