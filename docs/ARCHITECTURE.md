# SecureShip — Architecture & API Reference

Repo: `github.com/jav1d006/secureship` (branch `main`, protected: PR + CI required). Self-hosted DevSecOps scanner: upload a `.zip`, pick scanners, get a 0–100 score + findings.

## 1. System overview

| Component | Tech | Role | K8s object |
|---|---|---|---|
| Frontend | Next.js (App Router) | Scanner cards, upload, polling (1 s), results | Deployment `frontend` |
| API | FastAPI + Uvicorn (Py 3.12) | REST `/api/v1`, auth, rate limits, metrics | Deployment `backend` (node1, Recreate) |
| Worker | RQ worker (`python -m app.run_worker`) | Extract → scan → score → store | Deployment `worker` (node1) |
| Queue | Redis 7 (no persistence, 64 MB, optional password) | RQ queue `scans`, rate-limit counters | Deployment `redis` (node2) |
| DB | PostgreSQL 16 (psycopg 3 + pool) | Scans, results, uploads (BYTEA) | StatefulSet `postgres` (node2, 2 Gi PVC) |
| Metrics | Prometheus v2.55.1 (7 d, 2 Gi PVC) | Scrapes `backend:8000/metrics`, 8 alert rules | Deployment `prometheus` |
| Dashboards | Grafana 11.3.0 | Provisioned "SecureShip overview" | Deployment `grafana` (port-forward only) |
| Edge | ingress-nginx + MetalLB `192.168.0.200` (K8s); `nginx/` (compose) | Routing, limits, headers | Ingress `secureship`, `frontend` |
| GitOps | Argo CD (automated sync, self-heal, prune) | Applies `k8s/` from `main` | Application `secureship` |

```
User ─HTTP─> ingress-nginx ─/──────> frontend (Next.js)
                          └─/api,/health─> backend (FastAPI) ─┬─> PostgreSQL (scans, uploads)
                                                              └─> Redis ──RQ──> worker ─> PostgreSQL
worker ─> Gitleaks · Trivy(offline DB) · Bandit · Semgrep(offline rules) · Checkov · ShellCheck
Prometheus ─scrape─> backend:8000/metrics      Grafana ─> Prometheus      (no ingress; kubectl port-forward)
GitHub push ─> Actions (test · gitleaks · self-scan · image+SBOM+cosign) ─> GHCR ─pull─> cluster ; Argo CD syncs k8s/
```

## 2. Request lifecycle (scan)

| # | Step | Component |
|---|---|---|
| 1 | `POST /api/v1/scans` (zip + scanner list) validated: `.zip`, ≤ 25 MB, `PK\x03\x04` magic, known scanners, queue < `MAX_QUEUE`, rate limits | API |
| 2 | Row inserted (`status=queued`, upload in BYTEA, `owner` = SHA-256 of token); job `enqueue(scan_id)` (`job_timeout=600`) → `202 {id,status}` | API → PG, Redis |
| 3 | Worker loads upload, `set_running` (`attempts+1`, `started_at`), writes `WORK_DIR/<id>/upload.zip` | Worker |
| 4 | `safe_extract` (zip-slip, symlinks skipped, ≤ `MAX_FILES`, ≤ `MAX_UNZIPPED_MB` enforced while streaming) → `harden_tree` (no symlinks, no exec bits, 0600/0700) | Worker |
| 5 | `detect.inventory` (one walk, skips `.git`, `node_modules`, `vendor`…) → scanners with nothing to analyse are **skipped** | Worker |
| 6 | Selected scanners run in parallel threads (subprocesses); gates: `trivy` = 1 at a time, `heavy` (semgrep, checkov) = `HEAVY_CONCURRENCY` (1) | Worker |
| 7 | `overall_score` → `set_done(score, result JSONB)`; upload cleared; work dir deleted (`finally`) | Worker |
| 8 | Client polls `GET /api/v1/scans/{id}` until `done`/`failed` | Frontend / CLI |

Status machine: `queued → running → done | failed`. A failed scanner goes to `result.errors`; the scan still completes if at least one scanner produced results; if none did → `failed` with reason.

## 3. API reference

Base: `/api/v1` (OpenAPI UI: `/api/docs`, spec: `/api/openapi.json`). JSON unless noted. IDs: scan id = 32 hex chars. Content-Type of errors: `{"detail": "..."}`.

### 3.1 Identity & limits

| Item | Value |
|---|---|
| Web UI identity | HttpOnly cookie `ss_owner` (SameSite=Lax, 1 year, `Secure` if `COOKIE_SECURE=true`), created on first request |
| API identity | Header `X-API-Key: ss_<43 chars>` (bad format → `401`). Only SHA-256 of the token is stored (`scans.owner`) |
| Get a key | `POST /api/v1/keys` → `201 {"api_key": "ss_…"}` (shown once; **5/hour per IP**) |
| Ownership | Every scan query filters by owner; foreign or malformed IDs → `404` (no existence leak) |
| Reads | 240/min per owner |
| Scan creation | 10/hour per owner **and** 30/hour per IP; Redis down → `503` (fail closed). Other limits fail open |
| Over limit | `429` + `Retry-After` |
| Request size | `Content-Length` > `MAX_UPLOAD_MB`+1 MB → `413` |
| CORS | `CORS_ORIGINS`; methods GET/POST/DELETE; headers `Content-Type`, `X-API-Key`; credentials allowed |

### 3.2 Endpoints

| Method | Path | Auth | Purpose / params | Success | Errors |
|---|---|---|---|---|---|
| GET | `/health` | – | Liveness | `200 {"status":"ok"}` | – |
| GET | `/ready` | – | PG + Redis reachable (K8s readiness probe) | `200 {"status":"ready"}` | `503` |
| GET | `/metrics` | – (internal) | Prometheus text. **Not routed by ingress/nginx** | `200` | – |
| GET | `/api/v1/scanners` | owner | Catalog: `key,label,type,tool,description` | `200 [..]` | `429` |
| POST | `/api/v1/keys` | – | Issue API key | `201` | `429` |
| POST | `/api/v1/scans` | owner | multipart: `file` (.zip), `scanners` (csv, default `secrets`) | `202 {id,status:"queued"}` | `400` (not .zip / bad magic / unknown or empty scanner list), `413`, `429`, `503` (queue full / Redis down) |
| GET | `/api/v1/scans` | owner | `limit` 1–100 (20), `offset` ≥ 0. Fields: `id,filename,status,score,scanners,created_at,finished_at` | `200 [..]` | `429` |
| GET | `/api/v1/scans/{id}` | owner | Full scan incl. `result`, `error` | `200` | `404`, `429` |
| DELETE | `/api/v1/scans/{id}` | owner | Delete scan | `204` | `404` |
| GET | `/api/v1/scans/{id}/export?format=sarif\|csv\|json` | owner | SARIF 2.1.0 (`application/sarif+json`), CSV (formula-safe), JSON (= scan) | `200` (download) | `409` not finished, `404`, `422` bad format |
| POST | `/api/v1/scans/{id}/share` | owner | Create/return public badge token (idempotent) | `200 {badge_url, markdown}` | `404` |
| DELETE | `/api/v1/scans/{id}/share` | owner | Revoke badge | `204` | `404` |
| GET | `/api/v1/badge/{token}.svg` | public | Score-only SVG (token = 22 chars). 120/min per IP. `Cache-Control: public, max-age=300` | `200 image/svg+xml` | `404` |

### 3.3 Scan object

```jsonc
{ "id": "3f6c…(32 hex)", "filename": "project.zip", "status": "queued|running|done|failed",
  "score": 85,                       // null until done
  "scanners": "secrets,code",        // csv as requested
  "created_at": "2026-10-30T12:00:00+00:00", "finished_at": "…", "error": null,
  "result": {                        // null until done
    "modules": {"code": 85},         // per-module score (skipped modules excluded)
    "errors":  {"semgrep": "semgrep timed out"},
    "skipped": {"docker": "no Dockerfile found"},
    "timings": {"code": 5.3},        // seconds per scanner
    "code": {"findings": [ {"rule":"B602","description":"…","file":"a.py","line":7,
                            "severity":"critical|high|medium|low"} ]}
  } }
```

### 3.4 Response headers (all API responses)

`X-Content-Type-Options: nosniff` · `X-Frame-Options: DENY` · `Referrer-Policy: no-referrer` · `X-Robots-Tag: noindex, nofollow` · `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (not on `/api/docs`) · `Cache-Control: no-store` on `/api/v1/*` (except badge).

### 3.5 Quick use

```bash
KEY=$(curl -s -X POST $URL/api/v1/keys | jq -r .api_key)
ID=$(curl -s -H "X-API-Key: $KEY" -F file=@project.zip -F scanners=secrets,code,semgrep $URL/api/v1/scans | jq -r .id)
curl -s -H "X-API-Key: $KEY" $URL/api/v1/scans/$ID | jq '.status,.score'
curl -s -H "X-API-Key: $KEY" "$URL/api/v1/scans/$ID/export?format=sarif" -o result.sarif
```

GitHub Action: `uses: jav1d006/secureship@main` with `api-url`, `api-key`, `scanners`, `fail-under`, `sarif-file`, `timeout-seconds`; outputs `score`, `scan-id`. Script: `scripts/secureship-scan.sh` (`git archive HEAD` → upload → poll → fail below score).

## 4. Scanners & scoring

| Key | Tool | Looks at | Runs only if project has | Group |
|---|---|---|---|---|
| `secrets` | Gitleaks 8.28 (`--redact`) | Hard-coded secrets | always | – |
| `dependencies` | Trivy 0.58 `fs` (offline DB) | CVEs in lock/manifest files | requirements.txt, package-lock.json, go.mod, pom.xml, … | trivy |
| `code` | Bandit | Python SAST | `.py` | – |
| `iac` | Trivy `config` | Terraform, K8s, Helm, CFN | `.tf/.yaml/.yml/.bicep`, Dockerfile | trivy |
| `docker` | Trivy `config` (same run as `iac`) | Dockerfile rules | Dockerfile* | trivy |
| `semgrep` | Semgrep (`p/default` rules baked in, offline) | Multi-language SAST | supported source files | heavy |
| `checkov` | Checkov 3.4 (only detected frameworks) | IaC/CI policies | IaC or CI config files | heavy |
| `shell` | ShellCheck | `.sh/.bash` | shell scripts | – |

Adding a scanner: module with `run(path) -> {"findings":[…]}`, register in `scanners/__init__.py` (`SCANNERS`, `META`, optional `GROUPS`), add to `scoring.WEIGHTS` and `detect.RELEVANT`, add parser test.

| Severity | Penalty | | Module | Weight |
|---|---|---|---|---|
| critical | −25 | | secrets / dependencies | 25 / 25 |
| high | −15 | | iac / code / semgrep | 20 / 20 / 20 |
| medium | −7 | | checkov / docker / shell | 15 / 10 / 5 |
| low | −2 | | | |

Module score = `max(0, 100 − Σ penalties)`. Overall = weighted average over modules that ran (skipped/unselected excluded). Labels: ≥ 80 Excellent · ≥ 60 Good · ≥ 40 Needs improvement · < 40 Poor. Findings capped at 300 per module.

## 5. Data model (`scans`)

| Column | Type | Note |
|---|---|---|
| `id` | TEXT PK | uuid4 hex |
| `filename`, `scanners` | TEXT | sanitised name; csv keys |
| `status`, `score`, `error` | TEXT, INT, TEXT | |
| `result` | JSONB | see 3.3 |
| `upload` | BYTEA | **cleared after scan** (success or failure) |
| `owner` | TEXT | SHA-256 of cookie/API key; index `(owner, created_at DESC)` |
| `created_at`, `started_at`, `finished_at` | TEXT (ISO-8601 UTC) | cast `::timestamptz` in queries |
| `attempts` | INT default 0 | incremented per run |
| `share_token` | TEXT | unique partial index (non-null) |

Migrations: idempotent `CREATE/ALTER … IF NOT EXISTS` in `init_db()` at API start. Connection pool: `DB_POOL_MAX` (10), one pool per process (fork-safe).

## 6. Reliability

| Mechanism | Behaviour |
|---|---|
| Maintenance loop (API, every 300 s) | `fail_exhausted` (≥ 3 attempts, waiting or stuck → failed, upload dropped) · `reset_stuck` (`running` > 900 s → queued) · `requeue_unfinished` (> 60 s old, missing in Redis) · `purge_old` (done/failed > 30 d deleted) |
| Redis loss | Redis is ephemeral; unfinished scans are re-queued from PG on API start and by the loop |
| Scanner isolation | One scanner failing/timeouting (`SCAN_TIMEOUT_SEC` 120) never stops others |
| Queue protection | `MAX_QUEUE` 50 → `503` |
| Cleanup | Work dir removed in `finally`; `trivy_config` memo dropped per scan |

## 7. Security controls

| Area | Control |
|---|---|
| Untrusted uploads | Static analysis only (nothing executed/imported/installed); hardened unzip; size/count limits; worker has **no internet egress**; scanners offline (Trivy DB + Semgrep rules baked into image) |
| Secrets | Gitleaks `--redact`; upload deleted after scan; API keys stored hashed |
| Containers | Non-root UID 10001, read-only rootfs, caps dropped, seccomp RuntimeDefault, no SA token, resource limits, probes |
| Network | NetworkPolicy default-deny; allow: ingress-nginx → frontend/backend; backend+worker → PG 5432, Redis 6379, DNS; prometheus → backend 8000; grafana → prometheus 9090 |
| Edge (nginx/ingress) | Per-IP rate/conn limits, 26 MB body cap, hidden-file & backup-extension blocking (`/.git`, `.env`, `.bak`…), `/metrics` & `/ready` not exposed, CSP/HSTS/Permissions-Policy, `robots.txt` (`Disallow: /api/`), `/.well-known/security.txt` |
| Supply chain | Pinned deps, Gitleaks SHA-256 check, Trivy gate (HIGH/CRITICAL), SBOM (CycloneDX), cosign keyless signature, Dependabot (grouped, weekly) |
| Repo | `main` protected (PR + CI); `SECURITY.md`, `docs/THREAT_MODEL.md`, `CODEOWNERS` |

## 8. Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local PG | From secret `db-secret` |
| `REDIS_URL` / `REDIS_PASSWORD` | `redis://localhost:6379/0` / – | Password injected if URL has none (secret `redis-secret`, optional) |
| `CORS_ORIGINS` | `http://localhost:3000` | csv |
| `MAX_UPLOAD_MB` / `MAX_UNZIPPED_MB` / `MAX_FILES` | 25 / 100 / 5000 | Upload & extraction limits |
| `SCAN_TIMEOUT_SEC` / `HEAVY_CONCURRENCY` | 120 / 1 | Per-scanner timeout; Semgrep+Checkov at once |
| `RATE_SCANS_PER_HOUR` / `_IP` / `RATE_READS_PER_MIN` / `MAX_QUEUE` | 10 / 30 / 240 / 50 | Limits |
| `MAX_ATTEMPTS` / `STUCK_AFTER_SEC` / `RETENTION_DAYS` / `MAINTENANCE_INTERVAL_SEC` | 3 / 900 / 30 / 300 | Reliability |
| `DB_POOL_MAX` / `COOKIE_SECURE` | 10 / false | Pool size; `true` behind HTTPS |
| `WORK_DIR` / `DATA_DIR` | `/tmp/work` (k8s) / `./data` | Scratch dir |
| `*_BIN`, `SEMGREP_RULES` | in-image paths | Tool locations |

## 9. Kubernetes (namespace `secureship`)

| Object | Notes |
|---|---|
| `backend` | node1, 1 replica, Recreate, 128–384 Mi, probes `/ready` + `/health`, `/tmp` 256 Mi |
| `worker` | node1, 256 Mi req / **1 Gi** limit, 250 m CPU req; volumes `tmp` 1 Gi + **`trivy-cache` 3 Gi** (DB copied at start; fixes earlier "EmptyDir exceeds 1Gi" evictions) |
| `postgres` / `redis` | node2; non-root, read-only rootfs; PVC 2 Gi `local-path` / no persistence |
| `prometheus` / `grafana` | PVC 2 Gi, retention 7 d / 1 GB; Grafana needs secret `grafana-secret` (`ADMIN_PASSWORD`) |
| Secrets (created by hand, not in Git) | `db-secret` (required) · `redis-secret` (optional) · `grafana-secret` (required for Grafana) |
| Ingress | host `secureship.local` (hosts-file → `192.168.0.200`): `/api`, `/health` → backend; `/` → frontend; body ≤ 26 m; limit-rps 20 |
| Config as code | `monitoring/` is source of truth → `python monitoring/build_k8s.py` regenerates `k8s/monitoring-config.yaml` (a test enforces sync) |

## 10. CI/CD

| Job | What |
|---|---|
| `test` | pytest incl. PostgreSQL service container (`TEST_DATABASE_URL`) — 63 tests |
| `secrets` | Gitleaks over full history |
| `selfscan` | Trivy config + fs (HIGH/CRITICAL blocks), `promtool` lint + unit tests, Checkov (informational) |
| `image` / `frontend` | Build → Trivy image gate → SBOM artifact → (main) push GHCR `:latest` + `:<sha>` → cosign sign |
| Deploy | Argo CD syncs `k8s/` from `main`. Pods use `:latest` + `imagePullPolicy: Always`, so after CI pushes: `kubectl -n secureship rollout restart deploy/backend deploy/worker` |

## 11. Monitoring

| Metric | Type | Meaning |
|---|---|---|
| `secureship_queue_length` | gauge | Jobs in Redis |
| `secureship_scans{status}` | gauge | Rows per status |
| `secureship_oldest_queued_seconds` | gauge | Age of oldest queued scan |
| `secureship_scans_finished_last_hour{status}` | gauge | done / failed in last hour |
| `secureship_scan_duration_seconds_avg` | gauge | Avg scan time (1 h) |
| `secureship_scanner_duration_seconds_avg{scanner}` | gauge | Avg per scanner (1 h) |
| `secureship_dependency_up{dependency}` | gauge | postgres / redis reachable (`/metrics` never 500s) |
| `secureship_http_requests_total{method,route,status}` | counter | `/metrics` excluded |
| `secureship_http_request_seconds{route}` | histogram | Latency |

| Alert | Fires when | Sev |
|---|---|---|
| BackendDown | not scrapeable 2 m | critical |
| DependencyDown | PG/Redis down 2 m | critical |
| WorkerNotProcessing | oldest queued > 600 s for 5 m | critical |
| ScanQueueBacklog | queue > 30 for 10 m | warning |
| HighScanFailureRate | > 30 % failed (≥ 5 scans/h) 15 m | warning |
| SlowScans | avg > 120 s 15 m | warning |
| HighErrorRate | 5xx > 5 % 10 m | warning |
| HighLatencyP95 | p95 > 2 s 10 m | warning |

No Alertmanager yet: alerts are visible in Prometheus (`/alerts`) and Grafana only.

## 12. Operations cheat-sheet

```bash
kubectl -n secureship get pods
kubectl -n secureship logs deploy/worker --tail=50                      # scanner timings logged per scan
kubectl -n secureship delete pod --field-selector=status.phase=Failed  # clear evicted pods
kubectl -n secureship rollout restart deploy/backend deploy/worker     # pick up new :latest images
kubectl -n secureship port-forward --address 0.0.0.0 svc/grafana 3000:3000      # then http://<node1-ip>:3000
kubectl -n secureship port-forward --address 0.0.0.0 svc/prometheus 9090:9090
kubectl -n secureship get secret grafana-secret -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d; echo
kubectl -n argocd get app secureship                                    # Synced / Healthy
```

## 13. Repo layout

```
backend/app/   main.py (routes, metrics) · worker.py · db.py · security.py · export.py · safezip.py
               scoring.py · config.py · run_worker.py · scanners/ (gitleaks trivy trivy_config bandit semgrep checkov shellcheck detect)
backend/tests/ 63 tests (API, DB integration, scanners parsers, perf/gates, monitoring sync, export)
frontend/      Next.js app, public/{robots.txt,.well-known/security.txt}
k8s/           secureship.yaml (backend, ingress, netpols) · worker · data (pg, redis) · frontend · monitoring(-config) · netpol-egress
monitoring/    prometheus.yml · rules.yml · rules_test.yml · grafana/ · build_k8s.py
nginx/         compose edge config · action.yml + scripts/secureship-scan.sh · docs/THREAT_MODEL.md
.github/       workflows/ci.yml · dependabot.yml · CODEOWNERS · PR template
```

## 14. Known gaps / next steps

| Gap | Note |
|---|---|
| No accounts/teams/billing | Identity = anonymous token; token loss = scan loss |
| No TLS / real domain | `secureship.local` only; HSTS and `Secure` cookies inactive; GitHub Action cannot reach lab instance |
| Scan isolation | Scanners share the worker pod; SaaS needs per-scan sandbox (gVisor/Kata/K8s Job) |
| No Alertmanager | Alerts not delivered anywhere |
| UI | No buttons yet for SARIF export / badge; no history, triage, trends |
| Secrets & pins | Secrets created by hand; base images/actions pinned by tag, not digest |
| Lab limits | 1 replica each, local-path storage, 2 VirtualBox nodes (node1 ~4 GB RAM) |
