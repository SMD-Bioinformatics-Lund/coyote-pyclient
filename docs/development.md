# Develop the HTTP client

Run the following commands from the client repository root.
Python 3.12 or later and [uv](https://docs.astral.sh/uv/getting-started/installation/)
are required for these examples.

## Isolated editable installation

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[test]"
.venv/bin/python -m pytest -q tests/smoke
```

This environment installs only the client, HTTPX, Pydantic and test dependencies.
The API, core and database adapter are not required. Source edits take effect in
new processes without rebuilding a wheel. Reinstall after changing dependencies,
package metadata or entry points.

For coordinated server compatibility work, use a separate environment containing
this client and the candidate core/server artifacts. The application does not install
the client. The optional contract suite described below belongs to this repository.

## Tests and coverage

`tests/unit` checks synchronous and asynchronous authentication, resource access,
validation and transport failures. `tests/smoke` covers authenticated report-preview
transport. Both use HTTPX mock transports and synthetic responses; no running
server, database or credentials are needed.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q --cov --cov-config=pyproject.toml --cov-report=xml
```

Coverage includes the complete `coyote_pyclient` namespace and branches, with an
81% baseline floor. Outputs are `.coverage` and `coverage/coverage.xml`; add
`--cov-report=html` for `coverage/html/`. Smoke checks do not enforce full-suite coverage.

Keep synchronous and asynchronous behavior aligned for authentication, timeouts,
pagination, mutations and error handling. Preserve response validation and additive
server fields. New endpoints need synthetic success, permission and failure cases.

## Build

```bash
uv build --package coyote-pyclient
```

This produces a wheel and source distribution in `dist/`. The package has no
workspace dependency or parent-directory build hook. Test retained artifacts in
an isolated environment before release; see [releasing](releasing.md).

The `.github/workflows/quality.yml` workflow runs version/changelog checks, smoke
tests and a wheel build for development changes. Run full package coverage and
artifact checks locally before release.

## Server compatibility checks

`tests/server_contract` contains opt-in checks against installed Coyote core/server
artifacts. Install the candidate artifacts in a dedicated environment and run
`python -m pytest tests/server_contract`. These checks use synthetic HTTP transports
and do not contact a database or deployment. They are excluded from the default
client suite, which requires no application packages.
