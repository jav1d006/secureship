# Threat model

**Assets:** uploaded source code (high), scan results (medium), API keys / owner cookies (medium), cluster integrity (high).
**Trust boundaries:** Internet → edge (nginx / ingress) → API → Redis/Postgres ← worker → scanner subprocesses → untrusted archive contents.

| # | Threat (STRIDE) | Mitigation | Residual risk / gap |
|---|---|---|---|
| 1 | Zip-slip, symlinks, zip bombs (T, D) | `safezip`: path check, symlinks skipped, file/size limits enforced while streaming; `harden_tree` strips exec bits | Decompression CPU time bounded only by scan timeout |
| 2 | Malicious project executed by a scanner (E) | Static analysis only; no install/import/build; scanners run offline; worker has no egress and runs non-root, read-only rootfs, caps dropped; each scanner runs via `app/sandbox.py`: scrubbed env (no `DATABASE_URL`/`REDIS_*`), own process group killed on timeout, rlimits (CPU, file size, no core dumps) | Scanner parser bugs (Semgrep/Checkov/Trivy) — keep images rebuilt (Dependabot, weekly). In `SANDBOX_MODE=job` every scan runs in its own network-less Job with no credentials ([SANDBOX.md](SANDBOX.md)); in the default `local` mode a compromised scanner still shares the worker pod's network |
| 3 | Reading another user's scans (I) | 256-bit owner token, only SHA-256 stored; every query filters by owner; foreign IDs return 404 | Token loss = access loss (no accounts yet) |
| 4 | Abuse / resource exhaustion (D) | Edge limits (nginx/ingress) + per-owner and per-IP limits in Redis, queue cap, upload cap, per-scanner timeout, retry cap | Redis outage fails scan creation closed (503) by design |
| 5 | Poison archive crashes worker repeatedly (D) | `MAX_ATTEMPTS`, stuck-scan reaper, jobs are re-queued at most 3 times | — |
| 6 | Secret leakage via results/logs (I) | Gitleaks `--redact`; upload wiped after scan; retention job | Findings contain file names/paths |
| 7 | Redis tampering → code execution via RQ pickle (T, E) | NetworkPolicy (only API/worker), optional `requirepass` | Enable `redis-secret` in every real deployment |
| 8 | Tampered images / supply chain (T) | Pinned deps, Gitleaks checksum, Trivy gate, SBOM, keyless cosign signatures, Dependabot | Base images pinned by tag, not digest; actions pinned by tag |
| 9 | Web attacks on UI/API (T, I) | CSP, X-Frame-Options, nosniff, no-store on API, strict CORS, hidden-file/backup-file blocking at the edge, `robots.txt` + `X-Robots-Tag` | No TLS in the lab cluster (HSTS inactive until TLS) |
| 10 | Spoofed client IP to dodge limits (S) | Edge overwrites `X-Real-IP`/`X-Forwarded-For`; API trusts them only from ingress (NetworkPolicy) | With L2 MetalLB + `externalTrafficPolicy: Cluster` the source IP may be SNATed; use `Local` |
