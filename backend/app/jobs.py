"""Run one scan in its own Kubernetes Job (no network, no credentials, read-only source).

The worker and the Job share a volume: the worker extracts the archive to <id>/src, the Job
mounts it read-only, runs the scanners and writes <id>/out/result.json. Nothing the Job
returns is trusted: the file is size-capped and its shape validated before use.
"""
import json
import logging
import shutil
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from .scanners import SCANNERS

log = logging.getLogger("secureship.jobs")
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
MAX_OUT_BYTES = 8 * 1024 * 1024


class JobFailed(RuntimeError):
    pass


def job_name(scan_id: str) -> str:
    return f"scan-{scan_id[:24]}"


def build_job(scan_id: str, names: list[str]) -> dict:
    labels = {"app": "scan-job"}
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": job_name(scan_id), "namespace": config.SANDBOX_NAMESPACE, "labels": labels},
        "spec": {
            "backoffLimit": 0, "activeDeadlineSeconds": config.SANDBOX_JOB_TIMEOUT, "ttlSecondsAfterFinished": 300,
            "template": {"metadata": {"labels": labels}, "spec": {
                "restartPolicy": "Never", "automountServiceAccountToken": False, "enableServiceLinks": False,
                "nodeSelector": {"kubernetes.io/hostname": config.SANDBOX_NODE},
                "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                                    "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{
                    "name": "scan", "image": config.SANDBOX_IMAGE, "imagePullPolicy": "Always",
                    "workingDir": "/srv", "command": ["python", "-m", "app.run_scan_job"],
                    "env": [{"name": "SCAN_SCANNERS", "value": ",".join(names)},
                            {"name": "WORK_DIR", "value": "/tmp/work"}, {"name": "HOME", "value": "/tmp"}],
                    "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"memory": "1Gi"}},
                    "volumeMounts": [
                        {"name": "work", "mountPath": "/work/src", "subPath": f"{scan_id}/src", "readOnly": True},
                        {"name": "work", "mountPath": "/work/out", "subPath": f"{scan_id}/out"},
                        {"name": "tmp", "mountPath": "/tmp"},
                        {"name": "trivy-cache", "mountPath": "/tmp/trivy-cache"}],
                }],
                "volumes": [{"name": "work", "persistentVolumeClaim": {"claimName": config.SANDBOX_PVC}},
                            {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                            {"name": "trivy-cache", "emptyDir": {"sizeLimit": "3Gi"}}],
            }},
        },
    }


class KubeClient:
    """Just enough of the Kubernetes API for Jobs, using the pod's service-account token."""

    def __init__(self, base: str = "https://kubernetes.default.svc", token: str | None = None, ca: str | None = None):
        self.base = base
        self.token = token if token is not None else (SA / "token").read_text().strip()
        ca = ca if ca is not None else str(SA / "ca.crt")
        self.ctx = ssl.create_default_context(cafile=ca) if base.startswith("https") and Path(ca).exists() else None

    def _call(self, method: str, path: str, body: dict | None = None) -> dict | None:
        req = urllib.request.Request(self.base + path, method=method,  # noqa: S310
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15, context=self.ctx) as r:  # noqa: S310
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 404 and method != "POST":
                return None
            raise JobFailed(f"kubernetes API {method} {path}: {e.code}") from e

    def _jobs(self) -> str:
        return f"/apis/batch/v1/namespaces/{config.SANDBOX_NAMESPACE}/jobs"

    def create_job(self, spec: dict) -> None:
        self._call("POST", self._jobs(), spec)

    def get_job(self, name: str) -> dict | None:
        return self._call("GET", f"{self._jobs()}/{name}")

    def delete_job(self, name: str) -> None:
        self._call("DELETE", f"{self._jobs()}/{name}?propagationPolicy=Background")


def load_output(path: Path) -> tuple[dict, dict, dict, dict]:
    """Validate the Job's result file; it comes from a process that has read untrusted code."""
    if not path.is_file() or path.stat().st_size > MAX_OUT_BYTES:
        raise JobFailed("scan job produced no usable result")
    try:
        raw = json.loads(path.read_text())
        results = {n: {"findings": [f for f in r["findings"] if isinstance(f, dict)]}
                   for n, r in raw["results"].items() if n in SCANNERS and isinstance(r.get("findings"), list)}
        errors = {n: str(v)[:200] for n, v in raw["errors"].items() if n in SCANNERS}
        skipped = {n: str(v)[:200] for n, v in raw["skipped"].items() if n in SCANNERS}
        timings = {n: round(float(v), 2) for n, v in raw["timings"].items() if n in SCANNERS}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise JobFailed("scan job returned a malformed result") from e
    for n, r in raw["results"].items():       # keep any extra per-module keys (e.g. counts) the scanners emit
        if n in results:
            results[n].update({k: v for k, v in r.items() if k != "findings" and isinstance(v, (int, float, str))})
    return results, errors, skipped, timings


def run_in_job(scan_id: str, names: list[str], scan_dir: Path, client: KubeClient | None = None,
               poll: float = 1.0) -> tuple[dict, dict, dict, dict]:
    client = client or KubeClient()
    (scan_dir / "out").mkdir(mode=0o700, exist_ok=True)
    name = job_name(scan_id)
    try:
        client.create_job(build_job(scan_id, names))
        deadline = time.monotonic() + config.SANDBOX_JOB_TIMEOUT + 30
        while True:
            st = (client.get_job(name) or {}).get("status", {})
            if st.get("succeeded"):
                break
            if st.get("failed"):
                raise JobFailed("scan job failed or timed out")
            if time.monotonic() > deadline:
                raise JobFailed("scan job did not finish in time")
            time.sleep(poll)
        return load_output(scan_dir / "out" / "result.json")
    finally:
        try:
            client.delete_job(name)
        except Exception:
            log.warning("could not delete job %s", name)


def sweep(older_than: int = 3600) -> int:
    """Remove scan directories a crashed worker left on the shared volume."""
    n, root = 0, config.SANDBOX_WORK_DIR
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > older_than:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    return n
