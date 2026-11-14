# BOE Statistics notebooks

Two SQL stories use the public [v0.1.0 worker release](https://github.com/Query-farm/vgi-boe/releases/tag/v0.1.0), short visible ATTACH commands, and the shared [GitHub/Colab notebook standard](https://github.com/Query-farm/vgi-example-notebooks/blob/main/docs/standard.md).

| Notebook | Question and provenance | Experiment |
|---|---|---|
| [Reconcile Bank Rate changes](01_reconcile_bank_rate_changes.ipynb) | Do observed changes reconcile to the year-end difference? Unmodified official XML recorded on 14 November 2026, with original URLs, hashes and licence in [recordings](recordings/README.md). | YEAR 2024 → 2023 |
| [Publication time changes the comparison](02_publication_time_changes_the_comparison.ipynb) | Which values were published by a cutoff, and how do provisional values differ? Explicitly invented XML and fictional series isolate the worker's discovery, metadata and revision behavior. | AS_OF 15 March → 15 April 2024 |

Each notebook includes an **Open in Colab** button and can run without a worker checkout. The base shared package preserves compatible existing plotting/kernel libraries and fetches hash-verified companions. Local publication uses its separate runner extra:

```sh
cd notebooks
uv sync --locked
uv run --locked vgi-notebooks --timeout 300
uv run --locked vgi-notebooks 01_reconcile_bank_rate_changes.ipynb --parameters '{"YEAR":2023}' --output-dir artifacts/year-2023
uv run --locked vgi-notebooks 02_publication_time_changes_the_comparison.ipynb --parameters '{"AS_OF":"2024-04-15 12:00:00"}' --output-dir artifacts/april-cutoff
```

The visible worker location is `uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-boe@v0.1.0 vgi-boe-worker`. This tag resolves to `f0f6a7e195273a157536e838be0efd5f3655e1e8`; the release owns its runtime dependencies. Setup and analytical SQL remain visible on GitHub, which does not honor editor folding. SVG outputs also have content-addressed GitHub assets. Colab/Jupyter reruns produce native SVG.

### What the examples establish

The Bank Rate notebook retains a prior-December anchor, computes lag before filtering to the year and uses exact decimal values. Percent rate levels and basis-point changes are distinct: 100 basis points equal one percentage point. Missing calendar dates are not filled. Step lines guide the eye between returned observations, not announcements. The response's absent unit descriptor remains NULL; the rate unit is documented by [official Bank Rate history](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp).

The second notebook keeps observation periods, catalog-addition dates and publication times separate. It preserves provisional releases, then explicitly excludes them from its ordinary-value comparison. Missing periods stay NULL instead of zero. The cutoff experiment changes eligibility while keeping all six invented publication rows fixed. Those values do not describe the UK economy and do not establish the live service's available revision archive.

### Recorded and live execution

The first notebook's default replay verifies SHA-256 checksums and serves only exact manifest requests over loopback. The real released worker constructs requests and parses XML. Its optional `DATA_MODE="live"` removes inherited replay endpoint overrides and requests the same bounded windows from the official service, with verified TLS and no fallback. Existing `SSL_CERT_FILE` is honored, otherwise certifi supplies the CA bundle. Live availability depends on the upstream service and network.

```sh
uv run --locked vgi-notebooks 01_reconcile_bank_rate_changes.ipynb --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live-2024 --timeout 300
```

Both notebooks isolate SQL secrets and restore their own temporary configuration during cleanup. Source publication strings have no timezone inferred. Current historical downloads are not evidence of what was known at an earlier date.

### Coverage and validation

[Coverage evidence](coverage.json) separates the complete five-function released catalog from reviewed current source at `6f3a71aa6605563a28929bc470010b02b6e0b934`. All five have visible, interpreted SQL examples. Current changes add example/task metadata only; exact-current analytical execution is not claimed. Existing green source CI is reused because these changes affect notebooks only. Default and detached experiment runs, parameter guards, standalone preloaded-library bootstrap, chart review and actual GitHub SVG checks are recorded with the rollout evidence. Local bootstrap compatibility is not a hosted Colab execution claim.

Source data: Bank of England, copyright the Governor and Company of the Bank of England, reused under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/) subject to [database terms](https://www.bankofengland.co.uk/legal#bank-of-england-database). Worker and synthetic-fixture licensing remain separate. These examples do not imply Bank endorsement.
