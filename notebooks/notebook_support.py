"""Recorded/live setup and presentation; all rate calculations stay in SQL."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import certifi
import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display

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


def prose(text: str) -> None:
    display(Markdown(text))


def theme() -> None:
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.dpi": 145,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E8EDE9",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "text.parse_math": False,
            "legend.frameon": False,
        },
    )


def chart(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.91, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.10, 1, 0.83))
    fig.text(0.08, 0.03, source, fontsize=8, color="#6C7D73")
    plt.show()
