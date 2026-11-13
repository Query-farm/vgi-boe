"""Typed SQL functions for BoE discovery, observations and publication history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.invocation import BindResponse
from vgi.table_function import BindParams, OutputCollector, ProcessParams, TableFunctionGenerator, init_single_worker
from vgi_rpc import ArrowSerializableDataclass

from .api import bounds, codes, metadata, observations, request
from .meta import column, function_meta
from .transport import ApiError

DATASETS = pa.schema(
    [
        column("series_code", pa.string(), "Example official series code; discovery is curated, not exhaustive."),
        column("title", pa.string(), "Short curated description."),
        column("frequency", pa.string(), "Source frequency code."),
        column("source_url", pa.string(), "Official documentation and interactive catalog link."),
    ]
)
SERIES = pa.schema(
    [
        column("series_code", pa.string(), "BoE series identifier."),
        column("title", pa.string(), "Official series description."),
        column("description", pa.string(), "Concatenated source category descriptions."),
        column("frequency", pa.string(), "Source frequency code."),
        column("frequency_name", pa.string(), "Source frequency label."),
        column(
            "unit_descriptor",
            pa.string(),
            "OUTPUT IN category when provided; consult metadata for scale and conventions.",
        ),
        column("first_observation", pa.string(), "First recorded source period."),
        column("last_observation", pa.string(), "Last recorded source period."),
        column("categories_json", pa.string(), "All source categories, codes and labels."),
        column("metadata_json", pa.string(), "Source metadata hierarchy, including notes and definition links."),
    ]
)
COMMON = [
    *SERIES,
    column("period", pa.string(), "Original observation period."),
    column("observation_date", pa.date32(), "Calendar date assigned by the source to the period."),
    column("last_updated", pa.string(), "Source publication timestamp; no timezone is inferred."),
    column("confidentiality", pa.string(), "Original confidentiality flag."),
    column("details_json", pa.string(), "Observation attributes, footnotes and available revision hierarchy."),
]
OBSERVATIONS = pa.schema(
    [
        *COMMON,
        column("value", pa.float64(), "Official value in original units; NULL when absent."),
        column("value_text", pa.string(), "Exact original official numeric text."),
        column("provisional_value", pa.float64(), "Separately reported provisional value when requested."),
        column("provisional_value_text", pa.string(), "Exact provisional numeric text."),
    ]
)
REVISIONS = pa.schema(
    [
        *COMMON,
        column("published_at", pa.string(), "Source release timestamp, without an inferred timezone."),
        column("value", pa.float64(), "Published value in original units."),
        column("value_text", pa.string(), "Exact original published numeric text."),
        column("is_current", pa.bool_(), "Whether the release matches the returned current observation."),
        column("is_provisional", pa.bool_(), "Whether this is a separately provided provisional value."),
    ]
)


@dataclass(frozen=True, kw_only=True)
class BaseArgs:
    """Explicit bounded output."""

    max_rows: Annotated[
        int,
        Arg(
            "max_rows",
            default=100000,
            ge=1,
            le=1000000,
            doc=("Output cap after a complete bounded XML response; date and code arguments reduce source work."),
        ),
    ]


@dataclass(frozen=True, kw_only=True)
class DatasetArgs(BaseArgs):
    """Local curated catalog search."""

    query: Annotated[
        str,
        Arg(
            "query",
            default="",
            doc=("Case-insensitive local substring of code or title; empty returns all curated examples."),
        ),
    ]


@dataclass(frozen=True, kw_only=True)
class PeriodArgs(BaseArgs):
    """Required source date window."""

    start_date: Annotated[str, Arg("start_date", doc="Inclusive lower calendar bound in YYYY-MM-DD format.")]
    end_date: Annotated[str, Arg("end_date", doc="Inclusive upper calendar bound in YYYY-MM-DD format.")]


@dataclass(frozen=True, kw_only=True)
class DataArgs(PeriodArgs):
    """Selected series and publication filters."""

    series_codes: Annotated[
        list[str],
        Arg(
            0,
            arrow_type=pa.list_(pa.string()),
            doc="One to 300 distinct series codes, for example ['IUDBEDR'].",
        ),
    ]
    include_provisional: Annotated[
        bool, Arg("include_provisional", default=False, doc="Request separately reported provisional values.")
    ]
    updated_since: Annotated[
        str,
        Arg(
            "updated_since",
            default="",
            pattern=r"^(?:|latest|[0-9]{4}-[0-9]{2}-[0-9]{2})$",
            doc=(
                "Revision baseline: YYYY-MM-DD on or after 2007-06-03, latest, or empty for "
                "previous-release comparison."
            ),
        ),
    ]
    updates_only: Annotated[
        bool,
        Arg(
            "updates_only", default=False, doc="Request only observations changed since the selected revision baseline."
        ),
    ]


@dataclass(kw_only=True)
class State(ArrowSerializableDataclass):
    """A completion marker containing no source records or credentials."""

    done: bool = False


@init_single_worker
class BoeFunction[T: BaseArgs](TableFunctionGenerator[T, State]):
    """One bounded, validated source response per invocation."""

    FIXED_SCHEMA: ClassVar[pa.Schema]

    @classmethod
    def on_bind(cls, params: BindParams[T]) -> BindResponse:
        """Validate dates and series identifiers before network access."""
        args = params.args
        if isinstance(args, PeriodArgs):
            bounds(args.start_date, args.end_date, args.updated_since if isinstance(args, DataArgs) else "")
        if isinstance(args, DataArgs):
            codes(args.series_codes)
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def initial_state(cls, params: ProcessParams[T]) -> State:
        """Create an empty completion marker."""
        return State()

    @classmethod
    def fetch(cls, args: T) -> list[dict[str, Any]]:
        """Fetch a typed result from local discovery or the upstream API."""
        raise NotImplementedError

    @classmethod
    def process(cls, params: ProcessParams[T], state: State, out: OutputCollector) -> None:
        """Emit the complete validated result with an explicit user-selected cap."""
        if state.done:
            out.finish()
            return
        rows = cls.fetch(params.args)[: params.args.max_rows]
        try:
            batch = pa.RecordBatch.from_pylist(rows, schema=params.output_schema)
        except (pa.ArrowException, ValueError, OverflowError):
            raise ApiError("BoE response cannot be represented by the declared schema") from None
        state.done = True
        out.emit(batch)


class Datasets(BoeFunction[DatasetArgs]):
    """Curated starting points for official series discovery."""

    FIXED_SCHEMA = DATASETS
    Meta = function_meta(
        "datasets",
        "Discover BoE series examples",
        (
            "Search a small curated list of official series. This is not the complete BoE "
            "catalog; use the linked interactive database for all codes. No network request is "
            "made."
        ),
        DATASETS,
        "SELECT series_code, title FROM boe.main.datasets(query := 'rate') ORDER BY series_code",
    )

    @classmethod
    def fetch(cls, args: DatasetArgs) -> list[dict[str, Any]]:
        """Return known official example identifiers."""
        entries = [
            ("IUDBEDR", "Official Bank Rate", "D"),
            ("XUDLUSS", "US dollar spot exchange rate against sterling", "D"),
            ("LPMAUZI", "Monthly sterling M4 liabilities changes", "M"),
        ]
        return [
            {
                "series_code": code,
                "title": title,
                "frequency": frequency,
                "source_url": "https://www.bankofengland.co.uk/boeapps/database/",
            }
            for code, title, frequency in entries
            if args.query.casefold() in (code + " " + title).casefold()
        ]


def fetch_data(args: DataArgs, *, metadata_only: bool = False, revisions: bool = False) -> list[dict[str, Any]]:
    """Retrieve selected series with their original publication controls."""
    nodes = request(
        codes(args.series_codes),
        args.start_date,
        args.end_date,
        provisional=args.include_provisional,
        updated=args.updated_since,
        updates_only=args.updates_only,
    )
    return [metadata(n) for n in nodes] if metadata_only else observations(nodes, revisions=revisions)


class Series(BoeFunction[DataArgs]):
    """Discover source metadata for selected series."""

    FIXED_SCHEMA = SERIES
    Meta = function_meta(
        "series",
        "Inspect BoE series metadata",
        (
            "Retrieve titles, frequencies, categories, notes and definition links for selected "
            "codes within a required date window. Metadata is taken from the same XML download as "
            "observations; narrow dates reduce download size. series_codes is positional; dates "
            "and controls are named."
        ),
        SERIES,
        (
            "SELECT series_code, title, frequency FROM boe.main.series(['IUDBEDR'], start_date := "
            "'2024-01-02', end_date := '2024-01-05') ORDER BY series_code"
        ),
    )

    @classmethod
    def fetch(cls, args: DataArgs) -> list[dict[str, Any]]:
        """Read metadata without returning observation rows."""
        return fetch_data(args, metadata_only=True)


class Observations(BoeFunction[DataArgs]):
    """Current values with optional provisional values and revision details."""

    FIXED_SCHEMA = OBSERVATIONS
    Meta = function_meta(
        "observations",
        "Read BoE observations",
        (
            "Retrieve current observations in published units with exact numeric text, footnotes "
            "and publication timestamps. Provisional values occupy separate columns. Source "
            "timestamps have no inferred timezone. series_codes is positional; dates and controls "
            "are named."
        ),
        OBSERVATIONS,
        (
            "SELECT period, value FROM boe.main.observations(['IUDBEDR'], start_date := "
            "'2024-01-02', end_date := '2024-01-05') ORDER BY period"
        ),
    )

    @classmethod
    def fetch(cls, args: DataArgs) -> list[dict[str, Any]]:
        """Read current source observations."""
        return fetch_data(args)


class Revisions(BoeFunction[DataArgs]):
    """Published revisions exposed without inventing missing historical releases."""

    FIXED_SCHEMA = REVISIONS
    Meta = function_meta(
        "revisions",
        "Read BoE publication history",
        (
            "Flatten the revision entries returned by the XML service and include the current "
            "release once. Set updated_since to a historical baseline to request earlier "
            "revisions; empty uses the source's previous-release comparison. Coverage depends on "
            "the source and is not a complete ALFRED-style archive. series_codes is positional; "
            "dates and controls are named."
        ),
        REVISIONS,
        (
            "SELECT period, published_at, value FROM boe.main.revisions(['LPMAUZI'], start_date "
            ":= '2024-01-01', end_date := '2024-03-31', updated_since := '2024-01-01') ORDER BY "
            "period, published_at"
        ),
    )

    @classmethod
    def fetch(cls, args: DataArgs) -> list[dict[str, Any]]:
        """Read available publication history and the current release."""
        return fetch_data(args, revisions=True)


class NewSeries(BoeFunction[PeriodArgs]):
    """Metadata added to the source catalog within a date window."""

    FIXED_SCHEMA = SERIES
    Meta = function_meta(
        "new_series",
        "Discover newly added BoE series",
        (
            "Use the official SeriesCodes=all mode to list series added within the required "
            "start_date/end_date window. This discovers additions, not every existing series and "
            "not observations. Both dates are named arguments."
        ),
        SERIES,
        (
            "SELECT series_code, title FROM boe.main.new_series(start_date := '2024-01-01', "
            "end_date := '2024-01-31') ORDER BY series_code"
        ),
    )

    @classmethod
    def fetch(cls, args: PeriodArgs) -> list[dict[str, Any]]:
        """List source-reported catalog additions."""
        return [metadata(n) for n in request(None, args.start_date, args.end_date)]


FUNCTIONS: list[type[Any]] = [Datasets, Series, Observations, Revisions, NewSeries]
