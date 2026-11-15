"""Serve the Bank of England catalog over stdio, Unix sockets or HTTP.

Register new endpoints in functions.FUNCTIONS. Diagnostics use stderr; stdout
belongs exclusively to the VGI protocol when running over stdio.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from vgi import Worker
from vgi.catalog import Catalog, Schema

from .auth import validate_http_auth
from .functions import FUNCTIONS
from .meta import (
    CATALOG_COMMENT,
    CATALOG_NAME,
    CATALOG_TAGS,
    SCHEMA_CATEGORIES,
    SCHEMA_COMMENT,
    SCHEMA_DOC_LLM,
    SCHEMA_DOC_MD,
    SOURCE_URL,
    keywords_array,
)


def _stamp_example_queries(functions: list[type[Any]]) -> list[dict[str, str]]:
    """Publish each function's examples as ``vgi.example_queries`` (with descriptions).

    Overloads share one SQL name, so their examples are merged per name.
    Returns every example, for the schema-level list.
    """
    by_name: dict[str, list[dict[str, str]]] = {}
    for fn in functions:
        bucket = by_name.setdefault(fn.Meta.name, [])
        for ex in getattr(fn.Meta, "examples", []):
            entry = {"description": ex.description, "sql": ex.sql}
            if entry not in bucket:
                bucket.append(entry)
    for fn in functions:
        fn.Meta.tags = {**fn.Meta.tags, "vgi.example_queries": json.dumps(by_name[fn.Meta.name])}
    return [entry for entries in by_name.values() for entry in entries]


_ALL_EXAMPLES = _stamp_example_queries(FUNCTIONS)
CATALOG_TAGS["vgi.agent_test_tasks"] = json.dumps(
    [
        {
            "name": fn.Meta.name,
            "prompt": f"Using boe.main.{fn.Meta.name}, {fn.Meta.examples[0].description.lower()}. "
            f"Use the arguments in this example and return the same columns: {fn.Meta.examples[0].sql}",
        }
        for fn in FUNCTIONS
    ]
    + [
        {
            # Composed task: revision history (revisions) aligned with the policy rate (observations).
            "name": "m4_revision_counts_with_bank_rate",
            "prompt": (
                "For each Bank of England LPMAUZI (monthly M4 change) period from 2024-01-01 to 2024-03-31, "
                "using a revision baseline of 2024-01-01, return period (VARCHAR), releases (BIGINT: the number "
                "of revision rows published for that period), current_value (DOUBLE: the value of the current "
                "release) and bank_rate (DOUBLE: the latest non-NULL Official Bank Rate, series IUDBEDR, observed "
                "on or before the period's observation_date). Order by period."
            ),
        }
    ]
)


class BoeWorker(Worker):
    """The worker process: one catalog, one ``main`` schema."""

    catalog = Catalog(
        name=CATALOG_NAME,
        comment=CATALOG_COMMENT,
        source_url=SOURCE_URL,
        tags=CATALOG_TAGS,
        schemas=[
            Schema(
                path=["main"],
                comment=SCHEMA_COMMENT,
                functions=FUNCTIONS,
                tags={
                    "vgi.title": "BOE Functions",
                    "domain": "economics",
                    "vgi.keywords": keywords_array("boe, central bank, statistics, time series"),
                    "vgi.doc_llm": SCHEMA_DOC_LLM,
                    "vgi.doc_md": SCHEMA_DOC_MD,
                    "vgi.categories": json.dumps(SCHEMA_CATEGORIES),
                    "vgi.example_queries": json.dumps(_ALL_EXAMPLES),
                },
            )
        ],
    )


def main() -> None:
    """Console-script entry point: parse ``--http`` / ``--unix`` / logging flags and serve."""
    if "--http" in sys.argv[1:]:
        try:
            validate_http_auth()
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    BoeWorker.main()


if __name__ == "__main__":
    main()
