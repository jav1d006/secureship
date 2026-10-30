import json
import subprocess
import threading
from pathlib import Path

from .. import config
from .gitleaks import ScannerError
from .trivy import CACHE, SEV, ORDER, _ensure_cache


_memo: dict[str, object] = {}
_memo_lock = threading.Lock()


def forget(path: Path) -> None:
    """Drop the cached result of a finished scan."""
    _memo.pop(str(path), None)


def _scan(path: Path) -> list[dict]:
    """`trivy config` covers IaC and Dockerfiles in one pass; the iac and docker scanners
    share its result instead of running it twice. Failures are cached too (no second timeout)."""
    key = str(path)
    with _memo_lock:
        if key not in _memo:
            try:
                _memo[key] = _scan_uncached(path)
            except Exception as e:
                _memo[key] = e
        out = _memo[key]
    if isinstance(out, Exception):
        raise out
    return out


def _scan_uncached(path: Path) -> list[dict]:
    """IaC/Dockerfile misconfigurations via Trivy's built-in checks (offline)."""
    _ensure_cache()
    cmd = [config.TRIVY_BIN, "config", "--skip-check-update", "--cache-dir", str(CACHE),
           "--format", "json", "--quiet", "--no-progress",
           "--skip-dirs", "**/node_modules", "--skip-dirs", "**/.git", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.SCAN_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise ScannerError("trivy binary not found") from e
    except subprocess.TimeoutExpired as e:
        raise ScannerError("trivy timed out") from e
    if proc.returncode != 0:
        raise ScannerError(f"trivy failed: {proc.stderr.strip()[-200:]}")
    root, out = str(path), []
    for res in json.loads(proc.stdout or "{}").get("Results") or []:
        target = (res.get("Target") or "").removeprefix(root).lstrip("/")
        for m in res.get("Misconfigurations") or []:
            fix = f" Fix: {m['Resolution']}" if m.get("Resolution") else ""
            out.append({
                "rule": m.get("ID"),
                "description": (m.get("Title") or "Misconfiguration") + "." + fix,
                "file": target,
                "line": (m.get("CauseMetadata") or {}).get("StartLine") or 0,
                "severity": SEV.get(m.get("Severity"), "low"),
                "_docker": res.get("Type") == "dockerfile",
            })
    return out


def _pick(path: Path, docker: bool) -> dict:
    items = [f for f in _scan(path) if f["_docker"] == docker]
    items.sort(key=lambda f: ORDER.index(f["severity"]))
    return {"findings": [{k: v for k, v in f.items() if k != "_docker"} for f in items[:300]]}


def run_iac(path: Path, inv=None) -> dict:
    return _pick(path, docker=False)


def run_docker(path: Path, inv=None) -> dict:
    return _pick(path, docker=True)
