# Bank of England notebooks

[01 · Reconcile a year of Bank Rate changes](01_reconcile_bank_rate_changes.ipynb)
uses daily series **IUDBEDR**, a prior-December anchor and exact decimal SQL to
reconcile observed changes with the endpoint difference. Two figures show the
rate level and nonzero changes. Default outputs use unchanged official XML
recorded on **14 November 2026 UTC**, not synthetic data.

## Install and run

Install [uv](https://docs.astral.sh/uv/) and Git. This directory runs after being
copied away from the worker repository; it needs no parent source or root
Python environment. From here:

```sh
uv sync --locked
uv run --locked python execute.py --timeout 300
```

The separate lock pins Haybarn **2.0.0rc11**, JupySQL, plotting, execution tools and
the CA bundle. The runner creates a temporary kernel with its interpreter, uses
this directory as cwd, and replaces the saved notebook atomically after success.
Overrides require a separate destination. For an existing Jupyter frontend:

```sh
uv run --locked python -m ipykernel install --user \
  --name vgi-boe-notebooks --display-name "Python (vgi-boe notebooks)"
```

Select that kernel and **Restart Kernel → Run All** after editing parameters.
The runner does not register a global kernel. First runs require downloads.

## Literal remote worker launch

The visible SQL uses this location directly:

```text
uvx --python 3.13 --with vgi-python==0.51.1 --with vgi-rpc==0.53.1 --with pyarrow==26.0.1 --with defusedxml==0.7.1 --from git+https://github.com/Query-farm/vgi-boe@v0.1.0 vgi-boe-worker
```

Git tag **v0.1.0** resolves to **f0f6a7e195273a157536e838be0efd5f3655e1e8**. Runtime
pins match the tested source lock. uv installs the remote package into its own cache;
there is no local worker build or root environment discovery. The Python notebook
lock is separate and the repository's root lock is unchanged.

## Recorded and live data

`DATA_MODE = "recorded"` starts a small loopback HTTP server using the worker's
existing `BOE_API_BASE_URL` and explicit loopback-test flag. It serves byte-for-byte
official XML only when every request parameter matches the manifest. SHA-256
checksums are verified before startup. The real worker constructs the requests,
parses XML, preserves source metadata/numeric strings and emits its own Arrow rows.
No rates are computed or substituted by the replay server.

The [recording manifest](recordings/manifest.json) lists exact official URLs,
query parameters, UTC retrieval times, content types, byte counts and hashes.
Both 2023 and 2024 have a separate preceding-December response and selected-year
response. The source's daily revision-query path limits a request to one year,
so a combined year-plus-anchor request is not used. See the
[official download documentation](https://www.bankofengland.co.uk/boeapps/database/help.asp).

To request the same historical windows from the official service:

```sh
uv run --locked python execute.py --timeout 300 \
  --parameters '{"DATA_MODE": "live"}' --output-dir artifacts/live-2024
```

Live mode removes inherited endpoint/replay overrides, uses bounded retries and
request spacing, and never falls back to recordings. It keeps TLS verification
on, honors an existing trusted `SSL_CERT_FILE`, or uses the locked certifi bundle.
If your network needs an organization CA, supply its trusted bundle in that
environment variable. No upstream API key is needed. The execution timestamp is
UTC; source publication strings have no timezone inferred.

## Focused experiment

```sh
uv run --locked python execute.py --timeout 300 \
  --parameters '{"YEAR": 2023}' --output-dir artifacts/year-2023
```

`YEAR` accepts **2023 or 2024**, default **2024**. Keep recorded mode and predict a
change in the balance of increases/decreases. Compare signed net movement, gross
movement, event bars and the prior-December anchor. Both chart axes adapt to the
selected data; compare labelled values across runs. Reset to **2024**.

The runner copies the guide, helpers, recordings, manifest, lock and branding
beside experiment outputs. Generated logs, extracted figures and experiment copies
are ignored. Failed executions leave the successful default intact.

## Measurement and source limits

The analysis window is **1 January–31 December inclusive**. Fetch **1–31 December**
of the prior year separately and use its last returned observation as the anchor.
Dates are source calendar labels, not UTC instants. `lag()` runs before filtering
to the analysis year, so the first January value has a real predecessor.

Bank Rate is percent, as documented in the
[official Bank Rate history](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp).
The XML `unit_descriptor` is absent in these responses and is preserved as NULL;
it is not guessed from that field. One percentage point is 100 basis points.
`value_text` is parsed as DECIMAL(12,6), checked for precision preservation and used
for exact differences. The worker's Float64 convenience values are checked with
an absolute 1e-12 tolerance. Charts use numeric display conversions only.

The notebook stops if the expected series identity, usable values, precision,
anchor or output-cap checks fail. It does not interpolate missing values or invent
rows for absent calendar dates. Step connections are visual guides between
returned observations. A nonzero difference is an observed series change, not
independent evidence about announcement timing or causality. Source publication
strings remain unchanged, and a current historical download is not a vintage
archive of what was known in the past.

## Attribution and validation

Source data: Bank of England. Copyright the Governor and Company of the Bank of
England. Database data is reused under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/),
subject to the [database terms](https://www.bankofengland.co.uk/legal#bank-of-england-database).
The notebook's calculations and presentation do not imply Bank endorsement.
The worker's source license remains separate from the data license.

The repository's required `make check` passes formatting/lint, strict mypy,
pydoclint, **82 unit tests**, Haybarn SQL over stdio (**107 assertions**), Unix
launch (**107**) and HTTP (**71**), metadata **100/100, L2, zero findings**, and
stock DuckDB 2.0.0 stdio/authenticated-HTTP contracts. The official live worker path
is also tested. Notebook validation adds exact SQL reconciliation, recorded/live
execution, a detached year experiment, chart review and runner preservation guards.

To upgrade, change the visible worker pin, check SDK compatibility, and rerun both
years and live mode before replacing outputs. New recordings need explicit
provenance, checksums and source-license attribution. The community VGI extension
is downloaded independently of the Python lock. Unchanged Strata Sun and VGI
marks link to Query.Farm and VGI.
