# Validation — vgi-boe 0.1.0

Validated locally on 2026-11-13. All required gates passed.

- `make check`: **passed**; Ruff format/check, strict mypy and pydoclint are clean.
- Unit tests: **82 passed in 30.22s**.
- Haybarn 2.0.0rc11: stdio **107**, Unix launch **107**, HTTP **71** SQL assertions passed; zero unexpected skips.
- Metadata: **100/100, zero errors/warnings/info, assurance L2**, no waivers.
- Stock DuckDB 2.0.0, signed Query.Farm VGI **e75482339d**, macOS arm64: SQL contracts passed over stdio and authenticated HTTP.
- `make smoke-live`: **5** checks passed against the official API.
- `make package` and `ci/verify-artifacts.py --python 3.13`: wheel and locked source archive installed outside the checkout; SQL and bearer contracts passed for both.
- `uvx twine check dist/*`: both distributions passed metadata validation.
- `actionlint .github/workflows/*.yml`: passed.
- Docker image built with Python 3.13/Linux. Health returned 200, missing/wrong bearer tokens returned 401, authenticated stock-DuckDB catalog discovery found all five functions, and the container ran as UID 10001.

The development interpreter is Python 3.14; isolated artifact verification uses
Python 3.13. SDK: `vgi-python 0.51.1`, `vgi-rpc 0.53.1`.
The original Python starter baseline also passed before adaptation; starter revision
`9cca9105474d6e0052b8e343c8ea21f3d1a7503c` is recorded in `.vgi-starter.json`.

Machine-readable local evidence is in `build/` (ignored by Git):

| Report | Result | Checks |
|---|---|---|
| `container-verification.json` | passed | container health, bearer rejection and SQL catalog |
| `duckdb-verification.json` | passed | 14 |
| `http-auth-verification.json` | passed | 16 |
| `live-verification.json` | passed | 5 |
| `sdist-http-auth-verification.json` | passed | 16 |
| `sdist-verification.json` | passed | 14 |
| `wheel-http-auth-verification.json` | passed | 16 |
| `wheel-verification.json` | passed | 14 |

`build/check.log` contains the complete required gate output;
`build/artifact-sha256.json` identifies verified distributables in `dist/`.
`build/starter-baseline.log` records the unmodified starter baseline.
The metadata assurance does not include optional L3 agent/doc review.
Cross-platform CI is configured; local results do not claim that remote CI ran.
Live checks cover representative series, while deterministic fixtures cover
pagination, source errors, missing values and authentication failures.

Reproduce with:

```sh
make check
make smoke-live
make package
uv run python ci/verify-artifacts.py --python 3.13
```

Use the trusted system CA bundle through `SSL_CERT_FILE` when your Python
installation needs it. Local live checks used the Homebrew OpenSSL CA bundle;
TLS verification remained enabled. No upstream API keys are required.
