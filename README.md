<div align="center">

# 🛡️ SecureShip

**Open-source DevSecOps scanner. Pick your scanners, upload a project as a `.zip`, get a security score in seconds.**

[![CI](https://github.com/jav1d006/secureship/actions/workflows/ci.yml/badge.svg)](https://github.com/jav1d006/secureship/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-blue)
![Kubernetes](https://img.shields.io/badge/kubernetes-GitOps-326CE5?logo=kubernetes&logoColor=white)
![Argo CD](https://img.shields.io/badge/Argo%20CD-automated%20sync-EF7B4D?logo=argo&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-frontend-000000?logo=nextdotjs&logoColor=white)

<img src="docs/screenshots/home.png" alt="SecureShip home page" width="860">

</div>

---

## What is SecureShip?

SecureShip is a small, self-hosted security scanner built for teams that have no dedicated security engineer. You choose the scanners you want, upload your project as a ZIP archive, and SecureShip returns:

- a **Security Score (0–100)** with a per-module breakdown,
- a **severity-filtered list of findings** (file, line, rule, description, fixed version when known),
- the result of each tool, even if another tool fails.

> **Your code is only extracted and statically analysed. It is never executed or imported.** Secrets that are found are redacted, and the uploaded archive is deleted as soon as the scan finishes.

It is also a complete **DevSecOps reference project**: the application itself is built, scanned, shipped and deployed with the same practices it checks for (CI security gates, GitOps, least-privilege containers, default-deny networking).

## Scanners

| Key | Category | Tool | What it finds |
|---|---|---|---|
| `secrets` | Secrets detection | [Gitleaks](https://github.com/gitleaks/gitleaks) | Hard-coded API keys, tokens, passwords |
| `dependencies` | SCA | [Trivy](https://github.com/aquasecurity/trivy) | Known CVEs in libraries (`requirements.txt`, `package-lock.json`, `go.mod`, ...) |
| `code` | SAST | [Bandit](https://github.com/PyCQA/bandit) | Insecure patterns in Python source |
| `iac` | IaC | Trivy | Misconfigurations in Terraform, Kubernetes, Helm, CloudFormation |
| `docker` | Container | Trivy | Insecure Dockerfile instructions (root user, `latest` tags, `ADD` ...) |
| `semgrep` | SAST (multi-language) | [Semgrep](https://semgrep.dev) | Insecure patterns in JS/TS, Python, Go, Java, Ruby, PHP ... (OWASP rules baked into the image, runs offline) |
| `checkov` | IaC policies | [Checkov](https://www.checkov.io) | Terraform, Kubernetes, CloudFormation, GitHub Actions, GitLab CI, Ansible, OpenAPI ... |
| `shell` | Shell SAST | [ShellCheck](https://www.shellcheck.net) | Bugs and unsafe constructs in `.sh` / `.bash` scripts |

Scanners are pluggable: each one is a function `run(path) -> {"findings": [...]}` registered in `backend/app/scanners/__init__.py`. The frontend builds its scanner cards from `GET /api/scanners`, so adding a scanner needs **no frontend change**.

<div align="center">
<img src="docs/screenshots/results.png" alt="Scan results" width="860">
</div>

## Architecture

```mermaid
flowchart LR
    U([User]) -->|HTTP| ING[ingress-nginx<br/>MetalLB 192.168.0.200]
    ING -->|/| FE[Next.js frontend]
    ING -->|/api| API[FastAPI API]
    API -->|store upload + metadata| PG[(PostgreSQL)]
    API -->|enqueue job| R[(Redis)]
    R -->|RQ| W[Worker]
    W -->|read upload, write result| PG
    W --> G[Gitleaks]
    W --> T[Trivy offline DB]
    W --> B[Bandit]

    subgraph CI/CD
      GH[GitHub push] --> GA[GitHub Actions<br/>tests · Gitleaks · Trivy gate]
      GA -->|push image :sha| GHCR[(GHCR)]
    end
    GH -->|manifests in k8s/| ARGO[Argo CD]
    ARGO -->|automated sync| K8S{{Kubernetes cluster}}
    GHCR -.->|pull| K8S
```

**Request flow**

1. The browser asks `GET /api/scanners` and renders one card per scanner.
2. `POST /api/scans` (multipart: `file`, `scanners`) validates the input and stores the archive in PostgreSQL (`BYTEA`), then enqueues the scan ID in Redis (RQ).
3. A worker pops the job, writes the archive to an `emptyDir`, extracts it with a hardened unzip, runs each selected scanner (one failing scanner does not stop the others), computes the score and saves the result as `JSONB`.
4. The upload and the temporary directory are deleted. The frontend polls `GET /api/scans/{id}` and renders the result.

API and worker are separate Deployments that share nothing but PostgreSQL and Redis, so they can be scaled and restarted independently. Unfinished scans are automatically re-queued when the API starts (Redis is intentionally ephemeral).

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), React, plain CSS (light/dark), no UI libraries |
| API | Python 3.12, FastAPI, Uvicorn |
| Queue | Redis 7 + [RQ](https://python-rq.org/) |
| Database | PostgreSQL 16 (`psycopg` 3) |
| Scanners | Gitleaks 8.28, Trivy 0.58 (DB baked in, offline), Bandit, Semgrep, Checkov, ShellCheck (each Python tool in its own virtualenv) |
| Containers | Non-root images (frontend multi-stage), checksum-verified Gitleaks, pinned Python deps, published to GHCR |
| CI | GitHub Actions |
| CD | Argo CD (GitOps, automated sync, self-heal, prune) |
| Kubernetes | 2-node cluster (kubeadm/Kubespray-style) on VirtualBox: Calico, containerd, metrics-server, local-path-provisioner |
| Edge | MetalLB (L2) + ingress-nginx in Kubernetes; `nginx/` (hardened, unprivileged) in `docker compose` |
| Observability | Prometheus `/metrics`: queue length, scans by status, HTTP request count and latency per route |

## Security model

SecureShip is a security tool, so it is held to the standard it checks for.

**Handling untrusted uploads**
- Safe ZIP extraction: rejects path traversal (zip-slip), symbolic links, too many files, and archives that expand past a size limit (zip-bomb protection); entry sizes are enforced while streaming.
- Upload size limit (25 MB), extension check, scanner names validated against an allow-list.
- Static analysis only: nothing from the archive is executed, imported or installed.
- Gitleaks runs with `--redact`; secrets are never stored. The archive is wiped from the database and disk after every scan.

**Edge (nginx / ingress)**
- Per-IP rate limits (stricter for `POST /api/v1/scans` and `/api/v1/keys`), connection limits, 26 MB body cap, short header/body timeouts, unknown `Host` dropped (`444`), only `GET/HEAD/POST/DELETE/OPTIONS`.
- Hidden files (`/.git`, `/.env`, ...) and backup/config/key/source extensions return `404`; `autoindex off`; `/metrics` and `/ready` are not exposed.
- Security headers on every response (CSP for the UI, `nosniff`, `DENY` framing, no-referrer, Permissions-Policy, COOP/CORP, HSTS once TLS is in front); `server_tokens off`; client `X-Forwarded-For`/`X-Real-IP` are overwritten.
- `robots.txt` (`Disallow: /api/`), `/.well-known/security.txt` and `X-Robots-Tag: noindex` on API responses.

**Supply chain and CI gates**
- Every push runs unit + API + PostgreSQL integration tests, a Gitleaks secret scan and a **self-scan** (Trivy config/fs gate on this repo, Checkov), then builds the images.
- **Trivy blocks the pipeline on HIGH/CRITICAL** vulnerabilities in the built image (`--ignore-unfixed`); the image is only pushed to GHCR if the gate passes.
- Third-party scanner binaries (Gitleaks, Trivy) are excluded from the image gate with a documented reason: they run offline against files and expose no network services.
- Images are tagged with the commit SHA as well as `latest`; each build publishes a CycloneDX **SBOM** artifact and, on `main`, a keyless **cosign** signature.
- Gitleaks is checksum-verified, Python dependencies are pinned, Dependabot keeps pip/npm/docker/actions current.

**Runtime hardening (every pod)**
- `runAsNonRoot` (UID 10001), `allowPrivilegeEscalation: false`, all Linux capabilities dropped, `seccompProfile: RuntimeDefault`.
- `readOnlyRootFilesystem: true`; writable paths are explicit `emptyDir` mounts (`/tmp`).
- Resource requests and limits on every container.
- **NetworkPolicies: default deny**, then explicit allows only:
  - ingress-nginx → frontend / backend,
  - backend + worker → PostgreSQL (5432) and Redis (6379),
  - backend + worker → DNS (53).
  The worker (which processes untrusted files) has no route to the internet.
- Postgres and Redis run non-root with read-only root filesystem, dropped capabilities and probes; Redis supports `requirepass` (see below). No pod mounts a service-account token.
- Database credentials live in a Kubernetes Secret created out-of-band; they are **not** in Git.

## Reliability
- Scans are retried at most `MAX_ATTEMPTS` (3); a scan stuck in `running` longer than `STUCK_AFTER_SEC` is revived, then failed. A poison archive cannot loop forever.
- A maintenance loop in the API (`MAINTENANCE_INTERVAL_SEC`) re-queues scans Redis forgot and deletes finished scans older than `RETENTION_DAYS` (30).
- PostgreSQL access goes through a connection pool; the worker is a plain RQ worker (`python -m app.run_worker`).

## Security score

Each module starts at 100 and loses points per finding. The overall score is the **weighted average of the modules that actually ran**, so unselected scanners never distort the result.

| Severity | Penalty |
|---|---|
| critical | −25 |
| high | −15 |
| medium | −7 |
| low | −2 |

| Module | Weight |
|---|---|
| secrets | 25 |
| dependencies | 25 |
| iac | 20 |
| code | 20 |
| docker | 10 |
| semgrep | 20 |
| checkov | 15 |
| shell | 5 |

Labels: **≥ 80** Excellent · **≥ 60** Good · **≥ 40** Needs improvement · **< 40** Poor.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness/readiness |
| `GET` | `/metrics` | Prometheus metrics (`secureship_queue_length`, `secureship_scans{status}`) |
| `GET` | `/ready` | Readiness (PostgreSQL + Redis) |
| `GET` | `/api/docs` | OpenAPI UI |
| `GET` | `/api/v1/scanners` | Scanner catalog (key, label, type, tool, description) |
| `POST` | `/api/v1/keys` | Issue an API key (5/hour per IP); send as `X-API-Key` |
| `POST` | `/api/v1/scans` | Multipart form: `file` (`.zip`), `scanners` (comma-separated keys). Returns `202 {"id", "status"}` |
| `GET` | `/api/v1/scans` | Your scans (`limit`, `offset`) |
| `GET` | `/api/v1/scans/{id}` | Status, score and findings (owner only) |
| `DELETE` | `/api/v1/scans/{id}` | Delete a scan (owner only) |

Scans are bound to an owner: an HttpOnly cookie in the web UI or an `X-API-Key` header (only its SHA-256 is stored). Rate limits are per owner and per IP (`RATE_*` env vars); other owners get `404`.

```bash
KEY=$(curl -s -X POST http://secureship.local/api/v1/keys | jq -r .api_key)
curl -H "X-API-Key: $KEY" -F "file=@project.zip" -F "scanners=secrets,dependencies,code" \
     http://secureship.local/api/v1/scans
# {"id":"3f6c...","status":"queued"}

curl -H "X-API-Key: $KEY" http://secureship.local/api/v1/scans/3f6c...
```

## Repository layout

```
backend/
  app/
    main.py            FastAPI routes, metrics
    worker.py          RQ job: extract -> run scanners -> score -> store
    db.py              PostgreSQL access
    security.py        owner identity, API keys, rate limiting
    config.py          environment settings
    safezip.py         hardened ZIP extraction
    scoring.py         score model
    run_worker.py      RQ worker entrypoint
    scanners/          gitleaks, trivy, trivy_config, bandit, semgrep, checkov, shellcheck, registry (__init__.py)
  tests/               unit tests (pytest)
  Dockerfile
frontend/              Next.js app (scanner cards, drag & drop, results UI), public/ (robots.txt, security.txt)
nginx/                 hardened edge config for docker compose (limits, headers, hidden-file blocking)
docs/                  threat model, screenshots
k8s/                   Deployments, Services, Ingresses, NetworkPolicies, data layer
.github/workflows/     CI (tests, Gitleaks, Trivy gate, GHCR push)
```

## Run it yourself

### Prerequisites
A Kubernetes cluster with an ingress controller (this project uses ingress-nginx behind MetalLB), a default StorageClass (local-path-provisioner), Calico (or any CNI that enforces NetworkPolicy), Helm and Argo CD.

### Deploy

```bash
# 1. Namespace + database secret (kept out of Git)
kubectl create namespace secureship
PW=$(openssl rand -base64 24 | tr -d '=+/')
kubectl -n secureship create secret generic db-secret \
  --from-literal=POSTGRES_USER=secureship \
  --from-literal=POSTGRES_DB=secureship \
  --from-literal=POSTGRES_PASSWORD="$PW" \
  --from-literal=DATABASE_URL="postgresql://secureship:$PW@postgres:5432/secureship"

# 2. Let Argo CD deploy everything under k8s/
kubectl apply -f - <<'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: secureship, namespace: argocd}
spec:
  project: default
  source:
    repoURL: https://github.com/jav1d006/secureship.git
    targetRevision: main
    path: k8s
  destination: {server: https://kubernetes.default.svc, namespace: secureship}
  syncPolicy:
    automated: {prune: true, selfHeal: true}
    syncOptions: [CreateNamespace=true]
EOF

# 2b. Optional but recommended: Redis password (restart redis, backend and worker afterwards)
kubectl -n secureship create secret generic redis-secret \
  --from-literal=REDIS_PASSWORD="$(openssl rand -base64 24 | tr -d '=+/')"
kubectl -n secureship rollout restart deploy/redis deploy/backend deploy/worker

# 3. Point a hostname at the ingress IP (hosts file)
echo "192.168.0.200  secureship.local" | sudo tee -a /etc/hosts
```

Open <http://secureship.local>.

### Local development

```bash
docker compose up --build   # nginx edge :8080 -> frontend + API, worker, Postgres, Redis (dev credentials)
curl localhost:8080/health
```

`http://localhost:8080` serves the UI and the API through the same nginx rules used in production (`nginx/`).

### Run the tests

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/db pytest -q   # + PostgreSQL integration tests
```

## Screenshots

**GitOps with Argo CD**: the whole stack (ingress, frontend, backend, worker, PostgreSQL, Redis) is `Synced` and `Healthy`, deployed automatically from this repository.

<div align="center">
<img src="docs/screenshots/argocd.png" alt="Argo CD application tree" width="900">
</div>

## Known limitations

- Trivy needs lock files (`package-lock.json`, `requirements.txt`, `go.mod`, ...); a bare `package.json` is not enough.
- Bandit analyses Python only.
- The Trivy vulnerability database is baked into the image at build time, so rebuild the image regularly to stay current.
- The reference cluster is a two-node lab with limited RAM; a single replica of each component is used.
- Identity is an anonymous token (cookie / API key), not a user account; losing it loses access to your scans.
- Results are deleted automatically after `RETENTION_DAYS`; the SBOM/signature steps need the GitHub-hosted CI.
- Semgrep rules are fetched when the image is built; rebuild regularly (Dependabot + CI) to refresh them.
- No TLS in the lab cluster yet (cert-manager is on the roadmap), so HSTS and `Secure` cookies are inactive.

## Roadmap

- [ ] Commit-SHA image tags written back to Git by CI (fully hands-off GitOps)
- [ ] Prometheus + Grafana dashboards and alert rules
- [ ] HTTPS with cert-manager
- [ ] Scan a GitHub repository by URL / GitHub App for pull requests
- [ ] PDF report export
- [ ] User accounts
- [ ] Accounts, plans/quotas and billing (SaaS tier)
- [ ] Pin base images and actions by digest/SHA
- [ ] Sealed Secrets / SOPS for in-Git secrets

## Author

Designed and built by **Javid Mamedov** ([@jav1d006](https://github.com/jav1d006)).

## License

Released under the [MIT License](LICENSE).
