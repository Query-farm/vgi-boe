"""Recorded/live setup and presentation; all rate calculations stay in SQL."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import certifi
from recorded_api import RecordedApi

MANAGED = (
    "BOE_API_BASE_URL",
    "BOE_ALLOW_INSECURE_HTTP",
    "BOE_TIMEOUT_SECONDS",
    "BOE_MAX_ATTEMPTS",
    "BOE_RETRY_BUDGET_SECONDS",
    "BOE_MIN_INTERVAL_SECONDS",
    "BOE_MAX_RESPONSE_BYTES",
    "SSL_CERT_FILE",
)


def configure(year: int, mode: str):
    if type(year) is not int or year not in (2023, 2024):
        raise ValueError("YEAR must be 2023 or 2024; both have documented recording coverage")
    if mode not in ("recorded", "live"):
        raise ValueError("DATA_MODE must be 'recorded' or 'live'")
    previous = {key: os.environ.get(key) for key in MANAGED}
    for key in MANAGED:
        if key != "SSL_CERT_FILE":
            os.environ.pop(key, None)
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.update(
        BOE_TIMEOUT_SECONDS="20",
        BOE_MAX_ATTEMPTS="2",
        BOE_RETRY_BUDGET_SECONDS="50",
        BOE_MIN_INTERVAL_SECONDS="1",
        BOE_MAX_RESPONSE_BYTES=str(16 * 1024 * 1024),
    )
    replay = None
    run_at = datetime.now(UTC).isoformat()
    if mode == "recorded":
        replay = RecordedApi(Path(__file__).resolve().parent / "recordings", year).start()
        os.environ.update(
            BOE_API_BASE_URL=replay.url,
            BOE_ALLOW_INSECURE_HTTP="1",
            BOE_MIN_INTERVAL_SECONDS="0",
            BOE_MAX_ATTEMPTS="1",
        )
        captured = sorted({r["retrieved_at_utc"][:10] for r in replay.records.values()})
        provenance = "Recorded official XML · captured " + ", ".join(captured) + " UTC"
    else:
        provenance = "Live official XML · requested " + run_at[:19] + " UTC"
    return replay, previous, run_at, provenance


def cleanup(replay, previous):
    if replay:
        replay.stop()
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
