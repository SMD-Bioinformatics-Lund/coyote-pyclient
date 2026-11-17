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
2. Run this repository's optional `tests/server_contract` suite against the candidate server.
   Mock transport tests alone do not establish server compatibility.
3. Build the source distribution and wheel with `uv build --no-build-isolation`.
4. Install each artifact in a fresh environment with only its declared dependencies
   and test extras. Run the smoke suite and full client tests from outside the source
   checkout. Confirm that importing the client requires no core, server or database adapter.
5. Review a release PR from `dev` to `main`. After approval and merge, tag the
   release `vMAJOR.MINOR.PATCH` and retain the tested artifacts and release notes.

The smoke workflow does not publish to a package index. Package-index publication
requires a separately configured and approved release process.

## Integration adoption

External Python integrations may install a retained wheel or pin this repository
to an exact Git commit. The Coyote application does not install the Python client.
Development takes place on `dev`; publication and a release tag follow approval
of the release PR into `main`.

Before updating an integration's pin, run its workflows against the candidate
client and server. Use an authenticated Git credential helper while this repository
is private; never embed access tokens in dependency URLs, lockfiles or Docker layers.
A private repository also requires an explicit read credential in consuming CI.
