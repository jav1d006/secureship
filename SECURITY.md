# Security Policy

## Reporting a vulnerability
Please **do not open a public issue**. Report privately via
[GitHub Security Advisories](https://github.com/jav1d006/secureship/security/advisories/new).
Expect an acknowledgement within 72 hours and a fix or mitigation plan within 14 days for confirmed issues.

## Scope
| In scope | Out of scope |
|---|---|
| API, worker, scanners integration, ZIP handling | Findings reported *about scanned projects* (that is the product working) |
| Authentication/ownership bypass (IDOR), rate-limit bypass | Denial of service by volumetric traffic |
| Container / Kubernetes / CI configuration in this repo | Vulnerabilities in third-party tools without a SecureShip-specific impact |

## Supported versions
Only the latest commit on `main` and the images tagged `latest` / the latest commit SHA.

## Handling of uploaded code
Archives are extracted with a hardened unzip, analysed statically and deleted after the scan; secrets are redacted;
results are deleted after `RETENTION_DAYS` (default 30) or on request (`DELETE /api/v1/scans/{id}`).
See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
