"""Central bank values, pagination and authentication through real worker processes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from vgi.arguments import Arguments
from vgi.client import Client
from vgi.invocation import BindResponse

from boe_worker.auth import validate_http_auth
from boe_worker.functions import State
from test.mock_api.api_server import ApiServer


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiServer]:
    server = ApiServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("BOE_API_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("BOE_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("BOE_MIN_INTERVAL_SECONDS", "0")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def boe_client(api: ApiServer) -> Iterator[Client]:
    with Client([sys.executable, "-m", "boe_worker.worker"], pool=None) as client:
        yield client


def table(client: Client, name: str, *positional: Any, **named: Any) -> pa.Table:
    bound: list[BindResponse] = []
    batches = list(
        client.table_function(
            function_name=name,
            schema_path=["main"],
            bind_result_callback=bound.append,
            arguments=Arguments(
                positional=tuple(pa.scalar(v) for v in positional), named={k: pa.scalar(v) for k, v in named.items()}
            ),
        )
    )
    return pa.Table.from_batches(batches, schema=bound[-1].output_schema)


WORKER_TOKEN = "fixture-only-worker-token-with-32-characters"


@pytest.fixture()
def boe_http(api: ApiServer, tmp_path: Path) -> Iterator[str]:
    port_file = tmp_path / "port"
    environment = os.environ.copy()
    environment.update(VGI_BEARER_TOKENS=f"{WORKER_TOKEN}=analyst", VGI_PROXY_PROOF_MODE="off")
    environment.pop("VGI_JWT_ISSUER", None)
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "boe_worker.worker", "--http", "--port", "0", "--port-file", str(port_file)],
            stdout=log,
            stderr=log,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 20
            while not port_file.exists():
                assert process.poll() is None, "HTTP worker exited before publishing its port"
                if time.monotonic() >= deadline:
                    pytest.fail("HTTP worker did not start within 20 seconds")
                time.sleep(0.05)
            location = "http://127.0.0.1:" + port_file.read_text().strip()
            while True:
                try:
                    with urllib.request.urlopen(location + "/health", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() >= deadline:
                        pytest.fail("HTTP worker did not become ready")
                    time.sleep(0.05)
            yield location
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            messages = log.read()
            assert WORKER_TOKEN not in messages


@pytest.mark.parametrize("token", [None, "incorrect-token"])
def test_http_rpc_rejects_missing_or_wrong_bearer(boe_http: str, api: ApiServer, token: str | None) -> None:
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(boe_http + "/__describe__", headers=headers)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=5)
    assert exc.value.code == 401
    exc.value.close()
    with (
        pytest.raises(Exception, match="authentication rejected"),
        Client(transport="http", base_url=boe_http, bearer_token=token, pool=None) as client,
    ):
        table(client, "datasets")
    assert api.requests == []


def test_http_health_remains_available_without_bearer(boe_http: str) -> None:
    with urllib.request.urlopen(boe_http + "/health", timeout=5) as response:
        assert response.status == 200


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        ",",
        WORKER_TOKEN,
        "=analyst",
        f"{WORKER_TOKEN}=",
        "short=analyst",
        f"{WORKER_TOKEN}=analyst,",
        f"{WORKER_TOKEN}=analyst,{WORKER_TOKEN}=other",
    ],
)
def test_bad_bearer_configuration_fails_without_exposing_token(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VGI_BEARER_TOKENS", value)
    with pytest.raises(ValueError, match="Invalid VGI_BEARER_TOKENS") as exc:
        validate_http_auth()
    assert WORKER_TOKEN not in str(exc.value)


def test_bearer_configuration_accepts_multiple_principals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VGI_BEARER_TOKENS", f"{WORKER_TOKEN}=analyst,{WORKER_TOKEN}-second=service")
    validate_http_auth()
    monkeypatch.delenv("VGI_BEARER_TOKENS")
    validate_http_auth()


def test_bad_bearer_configuration_stops_http_startup(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["VGI_BEARER_TOKENS"] = WORKER_TOKEN
    port_file = tmp_path / "port"
    result = subprocess.run(
        [sys.executable, "-m", "boe_worker.worker", "--http", "--port-file", str(port_file)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode != 0
    assert "Invalid VGI_BEARER_TOKENS" in result.stderr
    assert WORKER_TOKEN not in result.stderr + result.stdout
    assert not port_file.exists()


def test_http_authenticated_data(boe_http: str, api: ApiServer) -> None:
    with Client(transport="http", base_url=boe_http, bearer_token=WORKER_TOKEN, pool=None) as client:
        result = table(client, "observations", ["IUDBEDR"], start_date="2024-01-01", end_date="2024-01-05")
    assert result.num_rows == 3
    assert len(api.requests) == 1
    assert all(WORKER_TOKEN not in str(record) for record in api.requests)


def test_state_roundtrip_has_no_values_or_credentials() -> None:
    state = State()
    assert State.deserialize_from_bytes(state.serialize_to_bytes()) == state
    assert not any("token" in name or "key" in name or "value" in name for name in state.__dataclass_fields__)


BOUNDS = {"start_date": "2024-01-01", "end_date": "2024-01-05"}


def test_local_discovery_and_series_metadata(boe_client: Client, api: ApiServer) -> None:
    assert table(boe_client, "datasets").num_rows == 3
    assert not api.requests
    row = table(boe_client, "series", ["IUDBEDR"], **BOUNDS).to_pylist()[0]
    assert row["title"] == "Fixture £ rate"
    assert row["frequency"] == "D"
    assert row["unit_descriptor"] == "Sterling"
    assert "Fixture £ notes" in row["metadata_json"]
    assert table(boe_client, "new_series", **BOUNDS).num_rows == 2
    assert api.requests[-1]["query"]["SeriesCodes"] == ["all"]


def test_observations_precision_nulls_and_provisional(boe_client: Client, api: ApiServer) -> None:
    result = table(boe_client, "observations", ["iudbedr"], include_provisional=True, **BOUNDS)
    assert result["value_text"].to_pylist() == ["2.50", None, "2.75"]
    assert result["value"].to_pylist() == [2.5, None, 2.75]
    assert result["provisional_value_text"].to_pylist() == ["2.80"] * 3
    assert result["observation_date"][0].as_py() == date(2024, 1, 2)
    assert "£ footnote" in result["details_json"][0].as_py()
    assert api.requests[-1]["query"]["Datefrom"] == ["01/Jan/2024"]
    assert api.requests[-1]["query"]["VFD"] == ["Y"]
    assert api.requests[-1]["query"]["VPD"] == ["Y"]
    assert table(boe_client, "observations", ["IUDBEDR"], max_rows=1, **BOUNDS).num_rows == 1
    assert table(boe_client, "observations", ["IUDBEDR"], start_date="2100-01-01", end_date="2100-01-02").num_rows == 0


def test_revisions_preserve_current_once_and_source_timestamps(boe_client: Client, api: ApiServer) -> None:
    result = table(boe_client, "revisions", ["LPMAUZI"], updated_since="2024-01-01", **BOUNDS).to_pylist()
    assert len(result) == 6
    assert sum(row["is_current"] for row in result) == 3
    assert result[0]["published_at"] == "2024-01-05 09:30:00"
    assert result[0]["value_text"] == "2.00"
    assert api.requests[-1]["query"]["VUDdate"] == ["01/Jan/2024"]
    assert (
        table(boe_client, "observations", ["IUDBEDR"], updates_only=True, updated_since="latest", **BOUNDS).num_rows
        == 1
    )
    assert api.requests[-1]["query"]["VUD"] == ["B"]


@pytest.mark.parametrize(
    "mode,match",
    [
        ("DUPLICATE", "duplicate"),
        ("BADVALUE", "numeric"),
        ("MISSING", "missing"),
        ("HTML", "envelope"),
        ("UNSAFE", "unsafe XML"),
        ("REDIRECT", "HTTP 302"),
        ("ERROR", "HTTP 400"),
    ],
)
def test_invalid_responses(boe_client: Client, api: ApiServer, mode: str, match: str) -> None:
    api.mode = mode
    with pytest.raises(Exception, match=match):
        table(boe_client, "observations", ["IUDBEDR"], **BOUNDS)


def test_retry(boe_client: Client, api: ApiServer) -> None:
    api.mode = "RETRY"
    assert table(boe_client, "observations", ["IUDBEDR"], **BOUNDS).num_rows == 3
    assert api.attempts == 2


@pytest.mark.parametrize("codes", [["IUDBEDR", "iudbedr"], ["../x"], ["IUDBEDR"] * 301, [None]])
def test_invalid_codes_before_network(boe_client: Client, api: ApiServer, codes: list[Any]) -> None:
    with pytest.raises(
        Exception, match=r"(?i)(series_codes|invalid|expected|must|none|null|period|date|timestamp|layer|argument)"
    ):
        table(boe_client, "observations", codes, **BOUNDS)
    assert not api.requests


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": "2024-02-30", "end_date": "2024-03-01"},
        {"start_date": "2024-02-01", "end_date": "2024-01-01"},
        {**BOUNDS, "updated_since": "2006-01-01"},
    ],
)
def test_invalid_dates_before_network(boe_client: Client, api: ApiServer, kwargs: dict[str, Any]) -> None:
    with pytest.raises(
        Exception, match=r"(?i)(series_codes|invalid|expected|must|none|null|period|date|timestamp|layer|argument)"
    ):
        table(boe_client, "observations", ["IUDBEDR"], **kwargs)
    assert not api.requests


def test_provisional_only_source_does_not_invent_official_release() -> None:
    from boe_worker.api import observations
    from boe_worker.xml import parse_xml

    root = parse_xml(
        b'<Envelope><Cube SCODE="IUDBEDR"><Cube TIME="2024-01-02" '
        b'PROV_VALUE="2.80" LAST_UPDATED="2024-01-03 09:30:00"/></Cube></Envelope>'
    )
    current = observations(list(root))
    assert current[0]["value"] is None and current[0]["provisional_value"] == 2.8
    releases = observations(list(root), revisions=True)
    assert len(releases) == 1 and releases[0]["is_provisional"] is True
