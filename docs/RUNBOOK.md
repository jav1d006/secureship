# Runbook

| Situation | Command |
|---|---|
| Restart app after new images | `kubectl -n secureship rollout restart deploy/backend deploy/worker` |
| Clean failed pods | `kubectl -n secureship delete pod --field-selector=status.phase=Failed` |
| API logs (JSON, filter by request) | `kubectl -n secureship logs deploy/backend \| grep <X-Request-ID>` |
| Queue / health | `curl -s secureship.local/ready` ; Grafana "SecureShip" dashboard |

## PostgreSQL backup
`CronJob/postgres-backup` (`k8s/backup.yaml`) runs daily 03:00 UTC: `pg_dump` → gzip → `pg-backups` PVC, keeps the last 7.

```bash
kubectl -n secureship create job --from=cronjob/postgres-backup backup-now   # run now
kubectl -n secureship logs job/backup-now                                    # "backup ok: ..."
```

Copy a dump off the cluster (the PVC lives on the same node as the database, so do this regularly):
```bash
kubectl -n secureship run bk --rm -it --restart=Never --image=busybox \
  --overrides='{"spec":{"volumes":[{"name":"b","persistentVolumeClaim":{"claimName":"pg-backups"}}],"containers":[{"name":"bk","image":"busybox","command":["sleep","600"],"volumeMounts":[{"name":"b","mountPath":"/backup"}]}]}}' -- ls -lh /backup
# in another terminal: kubectl -n secureship cp bk:/backup/<file>.sql.gz ./<file>.sql.gz
```

## Restore
```bash
kubectl -n secureship scale deploy/backend deploy/worker --replicas=0
kubectl -n secureship exec -i postgres-0 -- sh -c 'psql -U $POSTGRES_USER -d postgres -c "DROP DATABASE $POSTGRES_DB" -c "CREATE DATABASE $POSTGRES_DB"'
gunzip -c <file>.sql.gz | kubectl -n secureship exec -i postgres-0 -- sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=1'
kubectl -n secureship scale deploy/backend deploy/worker --replicas=1   # Argo CD would revert it anyway
```
Dump/restore round trip is verified in development. Redis holds only the queue; unfinished scans are re-queued automatically after a restore.

## API keys
Created/revoked from a browser session: `POST/GET /api/v1/keys`, `DELETE /api/v1/keys/{id}` (max `MAX_API_KEYS`=5 active). A key acts as the session that created it. Revoke a leaked key at once; keys issued before this feature keep working until revoked by redeploying with a new owner (they are not listed).

## Schema migrations (Alembic)
Migrations live in `backend/app/migrations/versions/`. API and worker run `alembic upgrade head` at startup (serialised by a Postgres advisory lock), so a new revision is applied by the first pod that starts.

| Task | Command (from `backend/`) |
|---|---|
| New migration | create `versions/000N_<name>.py` (copy `script.py.mako`; set `down_revision` to the previous id); use `IF NOT EXISTS` / reversible DDL |
| Current revision | `kubectl -n secureship exec -i postgres-0 -- sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "select * from alembic_version"'` |
| Apply by hand | `python -c "from app import db; db.init_db()"` |
| Rollback | restore the pre-deploy backup (see above); migrations are forward-only |

## E-mail the PDF report (optional)
Off by default (the button is hidden until a server is configured). Any SMTP server works (provider, Gmail app password, your own relay).
```bash
kubectl -n secureship create secret generic smtp-secret \
  --from-literal=SMTP_HOST=smtp.example.com --from-literal=SMTP_PORT=587 \
  --from-literal=SMTP_USER=apikey --from-literal=SMTP_PASSWORD='***' \
  --from-literal=SMTP_FROM='SecureShip <reports@example.com>'
kubectl -n secureship rollout restart deploy/backend
```
Limits per hour: 5 per scan owner, 10 per IP, 3 per recipient address (`RATE_EMAILS_PER_HOUR`). Only the owner's own finished scan can be sent.
