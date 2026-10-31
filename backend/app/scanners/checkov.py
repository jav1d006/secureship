import json
import subprocess
from pathlib import Path

from .. import config, sandbox
from . import detect
from .gitleaks import ScannerError

FRAMEWORKS = ("terraform,kubernetes,dockerfile,cloudformation,github_actions,gitlab_ci,"
              "arm,bicep,ansible,openapi,serverless")
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv"}
NOT_CONFIG = {"package.json", "package-lock.json", "tsconfig.json", "composer.json", "composer.lock"}
MAX_PROBE = 20000


def _has_config_files(root: Path) -> bool:
    """Checkov takes seconds just to start; skip it for projects without any IaC/CI/config files."""
    for i, p in enumerate(root.rglob("*")):
        if i > MAX_PROBE:
            return True     # huge tree: do not guess, scan it
        name, suf = p.name.lower(), p.suffix.lower()
        if not p.is_file() or SKIP_DIRS.intersection(p.relative_to(root).parts) or name in NOT_CONFIG:
            continue
        if suf in (".tf", ".tfvars", ".bicep", ".yaml", ".yml", ".json") or name.startswith("dockerfile") \
                or name.endswith(".dockerfile") or name == "containerfile":
            return True
    return False


SEV = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "INFO": "low"}
ORDER = ["critical", "high", "medium", "low"]


def run(path: Path, inv=None) -> dict:
    """IaC / CI-config policy scan with Checkov (parses files only; offline, nothing is executed)."""
    if not _has_config_files(path):
        return {"findings": []}
    env = {"BC_SKIP_MAPPING": "TRUE", "CHECKOV_RUN_SCA_PACKAGE_SCAN_V2": "false"}
    frameworks = detect.checkov_frameworks(inv) if inv is not None else FRAMEWORKS
    cmd = [config.CHECKOV_BIN, "-d", str(path), "--framework", frameworks,
           "--quiet", "--compact", "-o", "json", "--skip-download", "--skip-path", "node_modules", "--skip-path", "vendor"]
    try:
        proc = sandbox.run(cmd, config.SCAN_TIMEOUT_SEC, env)
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
