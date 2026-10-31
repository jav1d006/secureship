import json
import subprocess
from pathlib import Path

from .. import config, sandbox
from .gitleaks import ScannerError

LEVEL = {"error": "high", "warning": "medium", "info": "low", "style": "low"}
ORDER = ["critical", "high", "medium", "low"]
SKIP = {"node_modules", ".git", "venv", ".venv"}
MAX_FILES = 300


def _scripts(root: Path) -> list[str]:
    out = []
    for p in root.rglob("*"):
        if len(out) >= MAX_FILES:
            break
        if p.suffix in (".sh", ".bash") and p.is_file() and not p.is_symlink() \
                and not SKIP.intersection(p.relative_to(root).parts):
            out.append(str(p))
    return out


def run(path: Path) -> dict:
    """Shell-script linting with ShellCheck (static analysis; scripts are never executed or sourced)."""
    files = _scripts(path)
    if not files:
        return {"findings": []}
    cmd = [config.SHELLCHECK_BIN, "-f", "json", "--severity=info", *files]
    try:
        proc = sandbox.run(cmd, config.SCAN_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise ScannerError("shellcheck binary not found") from e
    except subprocess.TimeoutExpired as e:
        raise ScannerError("shellcheck timed out") from e
    if proc.returncode not in (0, 1, 2):    # 1 = issues, 2 = some file could not be parsed
        raise ScannerError(f"shellcheck failed: {proc.stderr.strip()[-200:]}")
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    root = str(path)
    findings = [{
        "rule": f"SC{r.get('code')}",
        "description": r.get("message") or "Shell issue",
        "file": (r.get("file") or "").removeprefix(root).lstrip("/"),
        "line": r.get("line") or 0,
        "severity": LEVEL.get(r.get("level"), "low"),
    } for r in data]
    findings.sort(key=lambda f: ORDER.index(f["severity"]))
    return {"findings": findings[:300]}
