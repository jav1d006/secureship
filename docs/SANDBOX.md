# Scan sandbox

| Mode | `SANDBOX_MODE` | Where scanners run | Isolation |
|---|---|---|---|
| local (default) | `local` | worker pod | scrubbed env, own process group, rlimits (`app/sandbox.py`); shares the worker's network |
| **job** | `job` | one Kubernetes Job per scan | no network at all, no credentials, no SA token, read-only source, only its own `<id>/` folders mounted, 1Gi RAM, deadline `SANDBOX_JOB_TIMEOUT` (600 s), auto-deleted |

## Flow (job mode)
```
worker: DB upload -> safe_extract -> /scan-work/<id>/src (shared PVC, node1)
worker: POST Job scan-<id> (label app=scan-job)         # RBAC: create/get/delete jobs only
Job   : python -m app.run_scan_job  -> /work/out/result.json   # src mounted read-only
worker: load_output() validates (size cap, scanner names, shapes) -> score -> DB; delete Job + folder
```
The Job's output is treated as untrusted. Orphan folders are swept at worker start (`jobs.sweep`, > 1 h old).

## Enable
| Step | Command |
|---|---|
| 1. Merge; Argo creates SA, Role, PVC `scan-work`, NetworkPolicy | `kubectl -n secureship get pvc scan-work sa/worker` |
| 2. Flip the mode (`k8s/worker.yaml`: `SANDBOX_MODE` → `job`) via PR, or test first | `kubectl -n secureship set env deploy/worker SANDBOX_MODE=job` (Argo self-heal reverts it; test only) |
| 3. Verify isolation | `kubectl -n secureship get jobs,pods -l app=scan-job` during a scan |
| 4. No network from a Job | `kubectl -n secureship run t --rm -it --restart=Never --labels=app=scan-job --image=busybox -- wget -T3 -O- http://redis:6379` → must time out |
| Roll back | `SANDBOX_MODE=local` |

## Trade-offs
| | |
|---|---|
| Latency | +3–10 s per scan (pod start; Trivy DB copied into the Job's `emptyDir`) |
| Worker privilege | worker holds a token able to create Jobs in this namespace only; it can no longer be treated as credential-free |
| Single node | worker, Jobs and the PVC are pinned to `node1` (`SANDBOX_NODE`) because `local-path` volumes are node-local |
| API egress rule | `allow-worker-to-kube-api` allows 443/6443 to private ranges; narrow to the API server IP if desired |
| Not covered | kernel/runtime escapes (add gVisor/Kata runtimeClass if available) |
