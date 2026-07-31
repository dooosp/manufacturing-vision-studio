# Security policy

## Supported scope

Security fixes are accepted for the current `main` branch and the latest
tagged demo release. Manufacturing Vision Studio is a local-first,
single-user portfolio demo. It is not a hosted service, a production
inspection system, a safety control, or an authorization to release parts.

The supported deployment boundary is loopback-only (`127.0.0.1`, `localhost`,
or `::1`) with data stored below a caller-selected local data directory. Remote
binding, multi-user authorization, shop-floor deployment, and field validation
are outside the supported scope.

## Reporting a vulnerability

Please use a private
[GitHub security advisory](https://github.com/dooosp/manufacturing-vision-studio/security/advisories/new).
Do not open a public issue for an undisclosed vulnerability.

Include, when possible:

- the affected commit or tag and operating system;
- a minimal reproduction using synthetic data;
- the expected and observed trust-boundary behavior;
- the security impact and any known preconditions; and
- a suggested remediation, if one is known.

Never include credentials, customer images, proprietary CAD, personal data, or
other private material in a report. A maintainer will respond on a best-effort
basis; this volunteer demo does not offer a response-time or remediation SLA.
Please allow coordinated disclosure until a fix or explicit risk statement is
available.

## Security invariants

- Default services bind only to loopback addresses.
- Image and evidence inputs are untrusted and must pass type, size, path,
  identity, schema, and hash validation before publication or import.
- Evidence verification and import fail closed and import is fail-atomic.
- Default setup, tests, demo, and CI require no secrets and make no external
  data download.
- Runtime databases, uploads, environment files, customer/private data, and
  generated output are excluded from version control.
- MVTec AD and other externally licensed datasets are never distributed by
  this repository; see [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).

Dependency or platform vulnerabilities should identify the exact locked
package and an upstream advisory when available. The project may reject a
report whose only claim assumes an unsupported public-network or production
deployment, but concrete defects in the documented boundary are welcome.
