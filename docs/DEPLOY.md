# Deploy

| Target | Command / path | Notes |
|---|---|---|
| Lab (VirtualBox, MetalLB, `secureship.local`) | Argo CD app, path `k8s` | current setup, `local-path` storage, `node1`/`node2` pinned |
| Cloud / own domain + TLS | Argo CD app, path `deploy/cloud` (or `kustomize build deploy/cloud \| kubectl apply -f -`) | real host, Let's Encrypt, default storage class, nothing pinned to a node |

## Move to a cloud cluster
| Step | Command |
|---|---|
| 1. Cluster add-ons | install **ingress-nginx** and **cert-manager** (Helm), point DNS `A`/`CNAME` of your domain at the ingress load balancer |
| 2. Your domain | `sed -i 's/secureship.example.com/app.yourdomain.com/g' deploy/cloud/kustomization.yaml` and set the e-mail in `deploy/cloud/cert-issuer.yaml` |
| 3. Check | `kustomize build deploy/cloud \| less` (host, `tls`, no `nodeSelector`, no `storageClassName`) |
| 4. Secrets (once, not in Git) | `db-secret`, optional `redis-secret`, `grafana-secret`, `smtp-secret`, `alertmanager-config` (see README, RUNBOOK) |
| 5. Deploy | create the Argo CD application with path `deploy/cloud`, or apply the kustomize output |
| 6. Verify | `kubectl -n secureship get certificate,ingress` → certificate `Ready`, then open `https://app.yourdomain.com` |

## What changes between lab and cloud
| Lab-specific | Cloud overlay does |
|---|---|
| host `secureship.local` | your domain + `tls` + `cert-manager.io/cluster-issuer` + HTTPS redirect |
| `storageClassName: local-path` | removed (cluster default class) |
| `nodeSelector` node1/node2 | removed |
| scan Jobs pinned to `node1` | `SANDBOX_NODE=""`: Jobs are scheduled next to the worker (pod affinity) because both mount one ReadWriteOnce volume |
| Redis/Postgres/Prometheus data on one node's disk | each gets a cloud volume; **keep the backup copied off-cluster** |

Not changed: images (`ghcr.io/jav1d006/...`), network policies, resource limits. Calico or another NetworkPolicy-capable CNI is still required for the default-deny policies to be enforced. Managed Postgres can replace the in-cluster one (set `DATABASE_URL` in `db-secret`, drop `postgres` from `k8s/data.yaml`).
