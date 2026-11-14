"""An explicitly invented two-clock BoE XML scenario, separate from official recordings."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring


def payload(selected, with_observations):
    """Return source-shaped XML; the real worker performs metadata/revision normalization."""
    root = Element("Envelope", {"xmlns": "http://www.gesmes.org/xml/2002-08-01"})
    for code in selected:
        monthly = code == "SYNINDEX"
        node = SubElement(
            root,
            "Cube",
            {
                "SCODE": code,
                "DESC": "Synthetic monthly index" if monthly else "Synthetic daily count",
                "CONCAT": "Entire response is authored, not observed economic data.",
            },
        )
        SubElement(node, "Cube", {"FREQ_CODE": "M" if monthly else "D", "FREQ_NAME": "Monthly" if monthly else "Daily"})
        SubElement(node, "Cube", {"CAT_NAME": "OUTPUT IN", "VAL_DESC": "Index points" if monthly else "Count"})
        SubElement(node, "Cube", {"FIRST_OBS": "2024-01-01" if monthly else "2020-01-01", "LAST_OBS": "2024-03-01"})
        SubElement(node, "SERIES_COM").text = "Fictional publication timestamps have no inferred timezone."
        if monthly and with_observations:
            for period, current, earlier, published in [
                ("2024-01-01", "12.00", "10.00", "2024-02-01 09:30:00"),
                ("2024-02-01", "18.00", "20.00", "2024-03-01 09:30:00"),
                ("2024-03-01", "30.00", None, None),
            ]:
                attrs = {"TIME": period, "OBS_VALUE": current, "LAST_UPDATED": "2024-04-01 09:30:00", "OBS_CONF": "N"}
                if period == "2024-03-01":
                    attrs["PROV_VALUE"] = "31.00"
                obs = SubElement(node, "Cube", attrs)
                if earlier is not None:
                    SubElement(obs, "Revision", {"UPDATE_TIMESTAMP": published, "OBS_VALUE": earlier})
                SubElement(obs, "Revision", {"UPDATE_TIMESTAMP": "2024-04-01 09:30:00", "OBS_VALUE": current})
    return tostring(root, encoding="utf-8", xml_declaration=True)


class SyntheticRevisions:
    """Serve only exact local discovery/history selectors and restore worker configuration."""

    def __init__(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith("BOE_")}
        for key in self._saved:
            os.environ.pop(key)
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):  # noqa: N802
                parsed = urlsplit(self.path)
                q = parse_qs(parsed.query, keep_blank_values=True)
                discovery = {
                    "CodeVer": ["new"],
                    "xml.x": ["yes"],
                    "Datefrom": ["01/Jan/2024"],
                    "Dateto": ["31/Jan/2024"],
                    "SeriesCodes": ["all"],
                }
                history = {
                    "CodeVer": ["new"],
                    "xml.x": ["yes"],
                    "Datefrom": ["01/Jan/2024"],
                    "Dateto": ["31/Mar/2024"],
                    "SeriesCodes": ["SYNINDEX"],
                    "VPD": ["Y"],
                    "VFD": ["Y"],
                    "VUD": ["A"],
                    "VUDdate": ["01/Jan/2024"],
                }
                if (
                    parsed.path != "/_iadb-fromshowcolumns.asp"
                    or self.headers.get("Authorization") is not None
                    or q not in (discovery, history)
                ):
                    self.send_error(400, "Request is outside the documented synthetic scenario")
                    return
                mode = "catalog-additions" if q == discovery else "publication-history"
                raw = payload(["SYNINDEX", "SYNCOUNT"] if q == discovery else ["SYNINDEX"], q == history)
                fixture.requests.append({"route": mode, "query": q, "response_bytes": len(raw)})
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        os.environ.update(
            BOE_API_BASE_URL=f"http://127.0.0.1:{self.server.server_port}",
            BOE_ALLOW_INSECURE_HTTP="1",
            BOE_MAX_ATTEMPTS="1",
            BOE_MIN_INTERVAL_SECONDS="0",
        )

    def close(self):
        """Stop only the owned server and restore prior environment without logging it."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for key in list(os.environ):
            if key.startswith("BOE_"):
                os.environ.pop(key)
        os.environ.update(self._saved)
