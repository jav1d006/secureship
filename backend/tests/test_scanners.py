"""Scanner output parsers, with the external binaries faked."""
import json
import subprocess
from types import SimpleNamespace

from app.scanners import bandit, gitleaks, trivy, trivy_config


def fake_run(stdout="", rc=0, write=None):
    def run(cmd, **kw):
        if write:
            path = cmd[cmd.index("--report-path") + 1]
            open(path, "w").write(json.dumps(write))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return run


def test_gitleaks_parses_and_strips_root(monkeypatch, tmp_path):
    raw = [{"RuleID": "aws-key", "Description": "AWS", "File": f"{tmp_path}/a/.env", "StartLine": 3}]
    monkeypatch.setattr(subprocess, "run", fake_run(write=raw))
    f = gitleaks.run(tmp_path)["findings"]
    assert f == [{"rule": "aws-key", "description": "AWS", "file": "a/.env", "line": 3, "severity": "high"}]


def test_bandit_parses_severity(monkeypatch, tmp_path):
    out = json.dumps({"results": [{"test_id": "B602", "issue_text": "shell", "filename": f"{tmp_path}/x.py",
                                   "line_number": 7, "issue_severity": "HIGH"}]})
    monkeypatch.setattr(subprocess, "run", fake_run(stdout=out, rc=1))
    f = bandit.run(tmp_path)["findings"]
    assert f[0]["severity"] == "high" and f[0]["file"] == "x.py" and f[0]["line"] == 7


def test_trivy_dedups_and_sorts(monkeypatch, tmp_path):
    v = lambda i, s: {"VulnerabilityID": i, "PkgName": "p", "InstalledVersion": "1", "Severity": s, "FixedVersion": "2"}
    out = json.dumps({"Results": [{"Target": "requirements.txt",
                                   "Vulnerabilities": [v("CVE-1", "LOW"), v("CVE-2", "CRITICAL"), v("CVE-2", "CRITICAL")]}]})
    monkeypatch.setattr(trivy, "_ensure_cache", lambda: None)
    monkeypatch.setattr(subprocess, "run", fake_run(stdout=out))
    f = trivy.run(tmp_path)["findings"]
    assert [x["rule"] for x in f] == ["CVE-2", "CVE-1"] and "fixed in 2" in f[0]["description"]


def test_trivy_config_splits_docker_and_iac(monkeypatch, tmp_path):
    m = {"ID": "DS002", "Title": "root", "Severity": "HIGH", "Resolution": "add USER"}
    out = json.dumps({"Results": [{"Target": "Dockerfile", "Type": "dockerfile", "Misconfigurations": [m]},
                                  {"Target": "k8s/a.yaml", "Type": "kubernetes", "Misconfigurations": [dict(m, ID="KSV1")]}]})
    monkeypatch.setattr(trivy_config, "_ensure_cache", lambda: None)
    monkeypatch.setattr(subprocess, "run", fake_run(stdout=out))
    assert [f["rule"] for f in trivy_config.run_docker(tmp_path)["findings"]] == ["DS002"]
    assert [f["rule"] for f in trivy_config.run_iac(tmp_path)["findings"]] == ["KSV1"]
