# Repository instructions

Coyote pyClient is an independent HTTP client. Keep its models, authentication,
transport, pagination and errors independent of Coyote core, server and databases.
Preserve synchronous/asynchronous parity, TLS verification and credential redaction.

## Development

- Work on a focused branch from `dev`; target development pull requests at `dev`.
- `main` is the release branch. Merge `dev` into `main` only after explicit release
  approval and successful validation. Never treat repository extraction as a release.
- Changelog headings, Git tags and release titles use `vMAJOR.MINOR.PATCH`.
  Python package metadata keeps the PEP 440 version without the `v` prefix.
- Preserve public interfaces and the approved README badges, logo and documentation
  layout unless a requested change explicitly alters them.
- Use typed Python, Google-style docstrings and the package's Ruff configuration.
  Validate external responses and preserve missing, null and zero distinctly.
- Add meaningful HTTPX mock-transport tests for behavior and failures. Run the
  package smoke suite, affected tests and full coverage before release.
- Keep clinical decisions and authorization on the server. A client filter is not
  an access-control boundary. Never expose unrestricted storage queries.
- Keep source, tests, documentation, changelog and GPL-3.0-only notices together.
  Do not add temporary probes, generators or application deployment scripts.

## Boundaries and release control

Use repository-relative paths. Operate only in this workspace unless the user
explicitly authorizes another resource. Do not contact deployments, databases or
servers without authorization; server inspection is read-only. Never publish
credentials, patient information or confidential fixtures. Use synthetic examples.
Push only when authorized. Only `ramsainanduri` is authorized to update protected
`main` and `dev`; do not weaken protections or bypass checks using another identity.
See `docs/development.md` and `docs/releasing.md` for verification and releases.
