# Release the Python client

The distribution `coyote-pyclient` and namespace `coyote_pyclient` have their own
version. Client 1.x targets the Coyote4 `/api/v1` HTTP contract. Application version
numbers do not determine the client version, and Coyote3 Flask routes are unsupported.

## Versioning

Use semantic versioning in `pyproject.toml`:

- Patch: compatible bug fixes.
- Minor: compatible new client functionality.
- Major: incompatible public interfaces or supported HTTP contracts.

Record user-visible changes in `CHANGELOG.md`. Keep the README version badges
consistent with the selected package version.

## Verification and release

1. Run all package tests with coverage using [development](development.md).
2. Run the application's client/API contract tests against the candidate server.
   Mock transport tests alone do not establish server compatibility.
3. Build the source distribution and wheel with `uv build --package coyote-pyclient`.
4. Install each artifact in a fresh environment with only its declared dependencies
   and test extras. Run the smoke suite and full client tests from outside the source
   checkout. Confirm that importing the client requires no core, server or database adapter.
5. Review a release PR from `dev` to `master`. After approval and merge, tag the
   release `vMAJOR.MINOR.PATCH` and retain the tested artifacts and release notes.

The smoke workflow does not publish to a package index. Package-index publication
requires a separately configured and approved release process.

## Application adoption

The Coyote application consumes this repository through an exact Git commit in
its uv sources and lockfile. Development takes place on `dev`; publication and a
release tag follow approval of the release PR into `master`.

Before updating an application pin, run its client/API contract tests against the
candidate client and server. Build retained deployment artifacts from that same
commit. Use an authenticated Git credential helper while this repository is
private; never embed access tokens in dependency URLs, lockfiles or Docker layers.
A private repository also requires an explicit read credential in consuming CI.
