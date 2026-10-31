import json
import subprocess
import tempfile
from pathlib import Path

from .. import config, sandbox


class ScannerError(Exception):
    pass


def run(path: Path) -> dict:
    """Run gitleaks as a static scan (no code is executed). Secrets are redacted."""
    with tempfile.TemporaryDirectory(prefix="gl-") as tmp:
        report = Path(tmp) / "report.json"
        cmd = [
            config.GITLEAKS_BIN, "dir", str(path),
            "--report-format", "json",
            "--report-path", str(report),
            "--redact",
            "--no-banner",
            "--exit-code", "0",
        ]
        try:
            proc = sandbox.run(cmd, config.SCAN_TIMEOUT_SEC)
        except FileNotFoundError as e:
            raise ScannerError("gitleaks binary not found") from e
        except subprocess.TimeoutExpired as e:
            raise ScannerError("gitleaks timed out") from e

        if proc.returncode != 0:
            raise ScannerError(f"gitleaks failed: {proc.stderr.strip()[:200]}")

        raw = []
        if report.exists() and report.stat().st_size:
            raw = json.loads(report.read_text() or "[]")

    root = str(path)
    findings = [
        {
            "rule": r.get("RuleID"),
            "description": r.get("Description"),
            "file": (r.get("File") or "").removeprefix(root).lstrip("/"),
            "line": r.get("StartLine"),
            "severity": "high",
        }
        for r in raw
    ]
    return {"findings": findings}
