# vgi-boe

Python VGI worker for Bank of England statistics. It exposes five typed SQL
functions with discovery metadata, original source values and HTTP bearer authentication.

## Executed notebooks

[Reconcile a year of Bank Rate changes](notebooks/README.md) uses official XML
recordings through the real worker, with exact SQL checks and a live option.

## Run locally

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
cd /absolute/path/to/vgi-boe
make build
```

Stock DuckDB 2.0.0 with the signed Query.Farm VGI extension:

```sql
SET allow_extension_repositories = 'allowed';
CREATE EXTENSION REPOSITORY IF NOT EXISTS query_farm
  WITH PREFIX 'https://duckdb-extensions.query.farm';
INSTALL vgi FROM query_farm;
LOAD vgi FROM query_farm;
ATTACH 'boe' (TYPE vgi,
  LOCATION '/absolute/path/to/vgi-boe/.venv/bin/vgi-boe-worker');

SELECT period, value, value_text, last_updated
FROM boe.main.observations(['IUDBEDR'],
  start_date := '2024-01-02', end_date := '2024-01-05')
ORDER BY period;
```

For Haybarn 2.0.0rc11, use its VGI extension and the same `ATTACH`/`SELECT` statements.
The worker can also use `launch:/absolute/path/to/worker` for Unix-socket pooling.
Diagnostics go to stderr; stdout belongs to Arrow IPC in stdio mode.

## SQL interface

| Function | Purpose |
|---|---|
| `datasets(query := '')` | Three curated starting series, with official discovery links. |
| `series(series_codes, start_date := ..., end_date := ...)` | Source descriptions, frequency, categories and notes. |
| `observations(series_codes, start_date := ..., end_date := ...)` | Current values, optional provisional values and footnotes. |
| `revisions(series_codes, start_date := ..., end_date := ...)` | Source publication history and the current release. |
| `new_series(start_date := ..., end_date := ...)` | Metadata for series added during the requested window. |

`series_codes` accepts 1–300 distinct codes; case is normalized. Required named
`start_date` and `end_date` use `YYYY-MM-DD`. `datasets` is explicitly curated,
not a full search index. Any valid official code can be queried; discover more
through the [official database](https://www.bankofengland.co.uk/boeapps/database/).
`new_series` uses the special `SeriesCodes=all` metadata mode, which means additions
in a window, not every existing series.

XML preserves richer metadata and publication history than CSV. `updated_since`
accepts an ISO date on or after 2007-06-03, `latest`, or the default empty value
(previous-release comparison). `updates_only := true` requests only changed
observations. The service restricts historical revision baselines to the previous
working day. Historical coverage is source-dependent, not a complete vintage archive.
The current release appears once when already present among revision entries.
Publication strings have no timezone inferred by this worker.

`include_provisional := true` requests provisional data in separate columns. The
source can replace an official value with a provisional value; in that case `value`
is NULL and `provisional_value` is populated. `unit_descriptor` comes from the
source OUTPUT IN category and may be absent. Consult the title and `metadata_json`
for scale and interpretation. No exchange rate inversion or rescaling is performed.

`max_rows` defaults to 100,000 (maximum 1,000,000). This caps emitted rows after a
complete bounded response; use date windows and code lists to control download size.
The XML service has no ordinary page-offset API. `series` downloads the same XML
response as observations, so narrow dates also reduce metadata-query cost.
Footnotes and linked definitions are preserved; links are never fetched automatically.

Official reference: [database and XML download documentation](https://www.bankofengland.co.uk/boeapps/database/help.asp).

## Authentication and deployment

The official upstream API is public and needs no API key. HTTP access to this
worker is a separate authentication boundary. Configure one or more strong bearer
tokens through `VGI_BEARER_TOKENS`, using `token=principal` pairs separated by commas:

```sh
# Inject real values from your deployment secret manager; do not commit them.
export VGI_BEARER_TOKENS="${WORKER_BEARER_TOKEN}=analytics"
.venv/bin/vgi-boe-worker --http --host 127.0.0.1 --port 8000
```

Tokens must contain 32–4096 characters from the documented bearer alphabet
(letters, digits, `.`, `_`, `~`, `+`, `/`, `-`), without `=`, commas or whitespace.
Malformed configuration stops startup without printing the token. Unset bearer
configuration leaves the SDK in its default anonymous mode: set it for shared
services. The SDK also supports OIDC/JWT configuration; this project's measured
authentication contract covers static bearer tokens, including multiple principals.
`/health` stays unauthenticated for readiness checks; RPC endpoints require the token.

```sql
INSTALL httpfs FROM core;
LOAD httpfs;
ATTACH 'boe' (TYPE vgi, LOCATION 'https://your-worker.example',
  bearer_token '<injected-worker-token>');
```

Use TLS at your reverse proxy for remote access, with restricted network ingress,
request/concurrency limits and a deployment secret manager. Process-local request
spacing does not coordinate across replicas; allocate a shared source request budget
at the deployment layer. No credentials are sent to the central bank or serialized
into continuation state. Query failures omit upstream response bodies and URLs.

```sh
docker build -t vgi-boe:local .
docker run --rm -p 127.0.0.1:8000:8000 \
  --env VGI_BEARER_TOKENS vgi-boe:local
# Stdio container transport:
docker run --rm -i vgi-boe:local stdio
```

The container uses Python 3.13, locked dependencies, an unprivileged UID and a
health check. Add platform resource limits appropriate to query concurrency and
response sizes. Do not publish unauthenticated containers directly to the Internet.

## Operations and data semantics

NULL SQL arguments are rejected. Missing observations become SQL NULL; original
numeric strings remain in `value_text` for explicit DECIMAL conversion. `value`
is a DOUBLE convenience column and has ordinary binary floating-point limits.
Units, frequency, seasonal-adjustment categories and source period conventions are
preserved, not harmonized across banks. Use function arguments for source filtering;
SQL `WHERE` clauses run after retrieval. An explicit `max_rows` cap intentionally
returns a subset; it is not an implicit source pagination limit.

Each source request has a timeout, bounded response size, retry budget, process-local
spacing and retries for 429/5xx/network failures. Retry-After is respected; a delay
beyond the budget fails the query instead of retrying early. Redirects are rejected.
Malformed or inconsistent responses fail visibly rather than becoming partial success.
There is no persistent cache or automatic background polling. SQL consumers should
use transactions/staging tables when persisting streamed results from an API.

| Environment setting | Default | Meaning |
|---|---|---|
| `BOE_API_BASE_URL` | Official API endpoint | Operator-controlled HTTPS override; no URL credentials, query or fragment. |
| `BOE_TIMEOUT_SECONDS` | 30 | Socket timeout (0.1–120 seconds). |
| `BOE_MAX_ATTEMPTS` | 4 | Attempts per page/request (1–6). |
| `BOE_RETRY_BUDGET_SECONDS` | 120 | Total request/retry budget (1–600 seconds). |
| `BOE_MIN_INTERVAL_SECONDS` | 1 | Minimum spacing between requests in one process (0–60 seconds). |
| `BOE_MAX_RESPONSE_BYTES` | 16 MiB | Response bound (1 KiB–64 MiB); narrow source selection on overflow. |
| `BOE_ALLOW_INSECURE_HTTP` | unset | `1` permits only explicit loopback HTTP fixtures. |

TLS certificate verification is always enabled. If a managed Python installation
cannot find your system CA store, point `SSL_CERT_FILE` at the trusted CA bundle;
do not disable verification. ECB and BoE XML parsers reject DTDs, entities and
external references. BoJ JSON parsing rejects non-finite numbers and preserves
fractional numeric lexemes before Arrow conversion.

## Verification and release

```sh
make check        # Ruff format/lint, mypy strict, pydoclint, pytest, real SQL, metadata
make smoke-live   # Explicit live checks against the official source
make package      # Wheel and source archive in dist/
uv run python ci/verify-artifacts.py --python 3.13
```

`make check` runs original starter and product SQL tests over Haybarn stdio, Unix
launch and HTTP, followed by metadata assurance L2 and stock DuckDB 2.0.0 over stdio
and authenticated HTTP. Fixtures are deterministic and do not require real keys.
The metadata gate fails on info findings and has no waivers. CI repeats checks on
Linux/Windows and Python 3.13/3.14, plus container and installed artifact contracts.
Local verification reports live in `build/`; see [VALIDATION.md](VALIDATION.md).

Starter: [Query.Farm Python starter](https://github.com/Query-farm/vgi-starter-python),
revision `9cca9105474d6e0052b8e343c8ea21f3d1a7503c`, template 1.3.0.
The locked SDK is `vgi-python 0.51.1` with `vgi-rpc 0.53.1`; keep those protocol
versions aligned with the tested extension. Original examples/tests remain under
`examples/starter_samples`, separate from this worker's public catalog.

The included release workflow gates tagged releases on CI and produces signed
artifacts and provenance. No remote repository, package publication or hosted
service is created by a local build. Source code is 0BSD; the banks' data terms
and attribution requirements apply separately. Source/API changes may require a
worker update. Report reproducible failures with a redacted query and source period,
without credentials or private server URLs.
