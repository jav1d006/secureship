# SecureShip

Open-source DevSecOps scanner: upload a repo ZIP, get a Security Score (0-100) and a findings list.
MVP: FastAPI + Gitleaks + SQLite + in-process queue. Runs on docker compose or a small k8s cluster.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/metrics` | Prometheus metrics |
| POST | `/api/scans` | multipart `file=<repo.zip>` → `202 {id, status}` |
| GET | `/api/scans` | recent scans |
| GET | `/api/scans/{id}` | status, score, per-module scores, findings |

## Run locally (docker compose)

```bash
docker compose up --build
curl http://localhost:8000/health
zip -r /tmp/test.zip some-project/
curl -F file=@/tmp/test.zip http://localhost:8000/api/scans
curl http://localhost:8000/api/scans/<id>
```

## Run tests

```bash
cd backend && pip install -r requirements.txt && pytest
```

## Deploy to the k8s cluster (node1/node2)

Image is built locally and imported into containerd (no registry needed yet). Run on **node1**:

```bash
docker build -t secureship-backend:dev backend
docker save secureship-backend:dev | sudo ctr -n k8s.io images import -
kubectl apply -f k8s/secureship.yaml
kubectl -n secureship get pods
```

Without Docker on node1: build elsewhere, `docker save -o img.tar`, copy to node1, then
`sudo ctr -n k8s.io images import img.tar`.

Prerequisite: `local-path` StorageClass (PVC stays Pending without it):

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
```

Test through ingress (`192.168.0.200  secureship.local` in hosts):

```bash
curl http://secureship.local/health
curl -F file=@test.zip http://secureship.local/api/scans
```

## Design notes

| Item | Choice |
|---|---|
| DB | SQLite on PVC (RAM-limited cluster); single replica, `Recreate` strategy |
| Queue | one worker thread in the API process; unfinished scans re-queued on restart |
| Upload safety | zip-slip, symlink, size/file-count limits; uploaded code is never executed; work dir deleted after scan |
| Secrets | gitleaks `--redact`; secret values are never stored |
| Pod hardening | non-root, read-only rootfs, drop ALL caps, seccomp, NetworkPolicy (ingress-nginx in, DNS out) |
| Score | per-module `100 - penalties`, weighted average over modules that ran |

## Roadmap

1. Frontend (Next.js) · 2. Trivy / Semgrep / Checkov · 3. PDF report · 4. Postgres + Redis · 5. Scan Jobs per pod · 6. Argo CD, Prometheus/Grafana, k6
