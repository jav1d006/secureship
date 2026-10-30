import json
import os
import subprocess
from pathlib import Path

from .. import config
from .gitleaks import ScannerError

FRAMEWORKS = ("terraform,kubernetes,dockerfile,cloudformation,github_actions,gitlab_ci,"
              "arm,bicep,ansible,openapi,serverless")
SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "INFO": "low"}
ORDER = ["critical", "high", "medium", "low"]


def run(path: Path) -> dict:
    """IaC / CI-config policy scan with Checkov (parses files only; offline, nothing is executed)."""
    env = {**os.environ, "HOME": "/tmp", "BC_SKIP_MAPPING": "TRUE", "CHECKOV_RUN_SCA_PACKAGE_SCAN_V2": "false"}
    cmd = [config.CHECKOV_BIN, "-d", str(path), "--framework", FRAMEWORKS,
           "--quiet", "--compact", "-o", "json", "--skip-download", "--skip-path", "node_modules"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=config.SCAN_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise ScannerError("checkov binary not found") from e
    except subprocess.TimeoutExpired as e:
        raise ScannerError("checkov timed out") from e
    if proc.returncode not in (0, 1):      # 1 = failed checks
        raise ScannerError(f"checkov failed: {proc.stderr.strip()[-200:]}")
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    reports = data if isinstance(data, list) else [data]    # one framework -> dict, several -> list
    findings = []
    for rep in reports:
        if not isinstance(rep, dict):
            continue
        for c in (rep.get("results") or {}).get("failed_checks") or []:
            res = c.get("resource")
            findings.append({
                "rule": c.get("check_id"),
                "description": (c.get("check_name") or "Policy violation") + (f" ({res})" if res else ""),
                "file": (c.get("file_path") or "").lstrip("/"),
                "line": (c.get("file_line_range") or [0])[0] or 0,
                # severity is only populated with a Prisma/Bridgecrew key; default to medium
                "severity": SEV.get((c.get("severity") or "").upper(), "medium"),
            })
    findings.sort(key=lambda f: ORDER.index(f["severity"]))
    return {"findings": findings[:300]}
