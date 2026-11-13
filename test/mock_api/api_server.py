"""Synthetic official API envelopes for offline SQL and authentication contracts."""

from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

API_KEY = "public-api-no-upstream-key"


class ApiServer(ThreadingHTTPServer):
    """Local service with controllable transport and response failures."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests: list[dict[str, Any]] = []
        self.mode = ""
        self.attempts = 0


class Handler(BaseHTTPRequestHandler):
    """Serve synthetic metadata and data without writing request logs."""

    server: ApiServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        self.server.requests.append({"path": url.path, "query": query})
        self.server.attempts += 1
        selected = query.get("SeriesCodes", ["IUDBEDR"])[0].split(",")
        mode = self.server.mode or (selected[0] if selected[0] not in {"IUDBEDR", "XUDLUSS", "LPMAUZI", "all"} else "")
        if selected == ["all"] and any(key in query for key in ("VPD", "VFD", "VUD")):
            mode = "REDIRECT"
        if selected == ["all"]:
            selected = ["IUDBEDR", "XUDLUSS"]
        root = Element("Envelope", {"xmlns": "http://www.gesmes.org/xml/2002-08-01"})
        for code in selected if mode != "MISSING" else []:
            series = SubElement(
                root,
                "Cube",
                {
                    "xmlns": "https://fixture.bankofengland.co.uk/website/agg_series",
                    "SCODE": code,
                    "DESC": "Fixture £ rate",
                    "CONCAT": "Fixture source scale",
                },
            )
            SubElement(series, "Cube", {"FREQ_CODE": "D", "FREQ_NAME": "Daily"})
            SubElement(series, "Cube", {"CAT_NAME": "OUTPUT IN", "CAT_VAL": "£", "VAL_DESC": "Sterling"})
            SubElement(series, "SERIES_COM").text = "Fixture £ notes"
            SubElement(series, "Cube", {"FIRST_OBS": "2000-01-01", "LAST_OBS": "2024-01-04"})
            for native, value in [("2024-01-02", "2.50"), ("2024-01-03", None), ("2024-01-04", "2.75")]:
                start = datetime.strptime(query["Datefrom"][0], "%d/%b/%Y").date().isoformat()
                end = datetime.strptime(query["Dateto"][0], "%d/%b/%Y").date().isoformat()
                if not start <= native <= end or (query.get("VUD") == ["B"] and native != "2024-01-04"):
                    continue
                attributes = {"TIME": native, "LAST_UPDATED": "2024-02-01 09:30:00", "OBS_CONF": "N"}
                if value is not None:
                    attributes["OBS_VALUE"] = "invalid" if mode == "BADVALUE" else value
                if query.get("VPD") == ["Y"]:
                    attributes["PROV_VALUE"] = "2.80"
                obs = SubElement(series, "Cube", attributes)
                SubElement(obs, "Footnote").text = "Fixture £ footnote"
                if query.get("VUDdate"):
                    SubElement(obs, "Revision", {"UPDATE_TIMESTAMP": "2024-01-05 09:30:00", "OBS_VALUE": "2.00"})
                    revision = {"UPDATE_TIMESTAMP": attributes["LAST_UPDATED"]}
                    if value is not None:
                        revision["OBS_VALUE"] = value
                    SubElement(obs, "Revision", revision)
                if mode == "DUPLICATE":
                    SubElement(series, "Cube", attributes)
        body = bytes(tostring(root, encoding="iso-8859-1", xml_declaration=True))
        status = 200
        if mode == "HTML":
            body = b"<html>Not an API response</html>"
        if mode == "UNSAFE":
            body = b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo>&x;</foo>'
        if mode == "RETRY" and self.server.attempts == 1:
            status, body = 429, b""
        if mode == "REDIRECT":
            status, body = 302, b""
        if mode == "ERROR":
            status, body = 400, b"invalid"
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        if status == 429:
            self.send_header("Retry-After", "0")
        if status == 302:
            self.send_header("Location", "https://example.invalid/")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ApiServer()
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()
