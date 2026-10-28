import json
import subprocess
import sys
from pathlib import Path

from .. import config
from .gitleaks import ScannerError

SEV = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


def run(path: Path) -> dict:
    """SAST for Python via Bandit (AST analysis only, the code is never imported or run)."""
    cmd = [
        sys.executable, "-m", "bandit", "-r", str(path), "-f", "json", "-q",
        "--skip", "B101", "-x", "*/node_modules,*/venv,*/.venv,*/tests,*/test",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.SCAN_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as e:
        raise ScannerError("bandit timed out") from e
    if proc.returncode not in (0, 1):      # 1 = issues found
        raise ScannerError(f"bandit failed: {proc.stderr.strip()[-200:]}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    root = str(path)
    findings = [
        {
            "rule": r.get("test_id"),
            "description": r.get("issue_text"),
            "file": (r.get("filename") or "").removeprefix(root).lstrip("/"),
            "line": r.get("line_number"),
            "severity": SEV.get(r.get("issue_severity"), "low"),
        }
        for r in data.get("results", [])
    ]
    return {"findings": findings}
