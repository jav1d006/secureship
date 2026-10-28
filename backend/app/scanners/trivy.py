import json
import shutil
import subprocess
from pathlib import Path

from .. import config
from .gitleaks import ScannerError

DB_SRC = Path("/opt/trivy-cache")      # vulnerability DB baked into the image
CACHE = Path("/tmp/trivy-cache")       # writable copy (root fs is read-only)
SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
ORDER = ["critical", "high", "medium", "low"]
MAX_FINDINGS = 300


def _ensure_cache() -> None:
    if (CACHE / "db" / "trivy.db").exists():
        return
    if not (DB_SRC / "db").exists():
        raise ScannerError("trivy vulnerability DB not found in image")
    shutil.copytree(DB_SRC, CACHE, dirs_exist_ok=True)


def run(path: Path) -> dict:
    """SCA: known vulnerabilities in dependency manifests. Offline, nothing is executed."""
    _ensure_cache()
    cmd = [
        config.TRIVY_BIN, "fs", "--scanners", "vuln",
        "--skip-db-update", "--skip-java-db-update", "--offline-scan",
        "--cache-dir", str(CACHE), "--format", "json", "--quiet", "--no-progress",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.SCAN_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise ScannerError("trivy binary not found") from e
    except subprocess.TimeoutExpired as e:
        raise ScannerError("trivy timed out") from e
    if proc.returncode != 0:
        raise ScannerError(f"trivy failed: {proc.stderr.strip()[-200:]}")

    data = json.loads(proc.stdout or "{}")
    root, seen, findings = str(path), set(), []
    for res in data.get("Results") or []:
        target = (res.get("Target") or "").removeprefix(root).lstrip("/")
        for v in res.get("Vulnerabilities") or []:
            key = (target, v.get("VulnerabilityID"), v.get("PkgName"))
            if key in seen:
                continue
            seen.add(key)
            fixed = v.get("FixedVersion")
            desc = f'{v.get("PkgName")} {v.get("InstalledVersion")}: {v.get("Title") or "vulnerable dependency"}'
            findings.append({
                "rule": v.get("VulnerabilityID"),
                "description": desc + (f" (fixed in {fixed})" if fixed else ""),
                "file": target, "line": 0,
                "severity": SEV.get(v.get("Severity"), "low"),
            })
    findings.sort(key=lambda f: ORDER.index(f["severity"]))
    return {"findings": findings[:MAX_FINDINGS]}
