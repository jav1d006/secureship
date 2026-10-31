import json
import subprocess
from pathlib import Path

from .. import config, sandbox
from .gitleaks import ScannerError

SEV = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
ORDER = ["critical", "high", "medium", "low"]


def run(path: Path) -> dict:
    """Multi-language SAST with Semgrep, using rules baked into the image (offline, no metrics)."""
    if not config.SEMGREP_RULES.exists():
        raise ScannerError("semgrep rules not found in image")
    env = {"SEMGREP_SEND_METRICS": "off"}
    cmd = [config.SEMGREP_BIN, "scan", "--config", str(config.SEMGREP_RULES), "--json", "--quiet",
           "--metrics", "off", "--disable-version-check", "--timeout", "10", "--jobs", "2", "--max-memory", "400",
           "--max-target-bytes", "1000000", "--exclude", "node_modules", str(path)]
    try:
        proc = sandbox.run(cmd, config.SCAN_TIMEOUT_SEC, env)
    except FileNotFoundError as e:
        raise ScannerError("semgrep binary not found") from e
    except subprocess.TimeoutExpired as e:
        raise ScannerError("semgrep timed out") from e
    if proc.returncode not in (0, 1):
        raise ScannerError(f"semgrep failed: {proc.stderr.strip()[-200:]}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        raise ScannerError("semgrep returned invalid output") from e
    root = str(path)
    findings = []
    for r in data.get("results") or []:
        extra = r.get("extra") or {}
        findings.append({
            "rule": (r.get("check_id") or "").rsplit(".", 1)[-1],
            "description": (extra.get("message") or "Insecure pattern")[:300],
            "file": (r.get("path") or "").removeprefix(root).lstrip("/"),
            "line": (r.get("start") or {}).get("line") or 0,
            "severity": SEV.get((extra.get("severity") or "").upper(), "low"),
        })
    findings.sort(key=lambda f: ORDER.index(f["severity"]))
    return {"findings": findings[:300]}
