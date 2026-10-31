"""Scanner output parsers, with the external binaries faked."""
import json
from types import SimpleNamespace

from app import sandbox
from app.scanners import bandit, gitleaks, trivy, trivy_config


def fake_run(stdout="", rc=0, write=None):
    def run(cmd, timeout=None, env=None, **kw):
        if write:
            path = cmd[cmd.index("--report-path") + 1]
            open(path, "w").write(json.dumps(write))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return run


def test_gitleaks_parses_and_strips_root(monkeypatch, tmp_path):
    raw = [{"RuleID": "aws-key", "Description": "AWS", "File": f"{tmp_path}/a/.env", "StartLine": 3}]
    monkeypatch.setattr(sandbox, "run", fake_run(write=raw))
    f = gitleaks.run(tmp_path)["findings"]
    assert f == [{"rule": "aws-key", "description": "AWS", "file": "a/.env", "line": 3, "severity": "high"}]


def test_bandit_parses_severity(monkeypatch, tmp_path):
    out = json.dumps({"results": [{"test_id": "B602", "issue_text": "shell", "filename": f"{tmp_path}/x.py",
                                   "line_number": 7, "issue_severity": "HIGH"}]})
    monkeypatch.setattr(sandbox, "run", fake_run(stdout=out, rc=1))
    f = bandit.run(tmp_path)["findings"]
    assert f[0]["severity"] == "high" and f[0]["file"] == "x.py" and f[0]["line"] == 7


def test_trivy_dedups_and_sorts(monkeypatch, tmp_path):
    v = lambda i, s: {"VulnerabilityID": i, "PkgName": "p", "InstalledVersion": "1", "Severity": s, "FixedVersion": "2"}
    out = json.dumps({"Results": [{"Target": "requirements.txt",
                                   "Vulnerabilities": [v("CVE-1", "LOW"), v("CVE-2", "CRITICAL"), v("CVE-2", "CRITICAL")]}]})
    monkeypatch.setattr(trivy, "_ensure_cache", lambda: None)
    monkeypatch.setattr(sandbox, "run", fake_run(stdout=out))
    f = trivy.run(tmp_path)["findings"]
    assert [x["rule"] for x in f] == ["CVE-2", "CVE-1"] and "fixed in 2" in f[0]["description"]


def test_trivy_config_splits_docker_and_iac(monkeypatch, tmp_path):
    m = {"ID": "DS002", "Title": "root", "Severity": "HIGH", "Resolution": "add USER"}
    out = json.dumps({"Results": [{"Target": "Dockerfile", "Type": "dockerfile", "Misconfigurations": [m]},
                                  {"Target": "k8s/a.yaml", "Type": "kubernetes", "Misconfigurations": [dict(m, ID="KSV1")]}]})
    monkeypatch.setattr(trivy_config, "_ensure_cache", lambda: None)
    monkeypatch.setattr(sandbox, "run", fake_run(stdout=out))
    assert [f["rule"] for f in trivy_config.run_docker(tmp_path)["findings"]] == ["DS002"]
    assert [f["rule"] for f in trivy_config.run_iac(tmp_path)["findings"]] == ["KSV1"]


def test_checkov_handles_dict_and_list_shapes(monkeypatch, tmp_path):
    from app.scanners import checkov
    (tmp_path / "a.yaml").write_text("kind: Pod")
    fc = {"check_id": "CKV_K8S_9", "check_name": "Readiness probe", "file_path": "/k8s/a.yaml",
          "file_line_range": [4, 20], "severity": None, "resource": "Deployment.default.a"}
    for payload in ({"results": {"failed_checks": [fc]}},
                    [{"results": {"failed_checks": [fc]}}, {"results": {"failed_checks": [dict(fc, severity="HIGH", check_id="X")]}}]):
        monkeypatch.setattr(sandbox, "run", fake_run(stdout=json.dumps(payload), rc=1))
        f = checkov.run(tmp_path)["findings"]
        assert f[0]["file"] == "k8s/a.yaml" and f[0]["line"] == 4 and "Deployment.default.a" in f[0]["description"]
    assert f[0]["severity"] == "high" and f[1]["severity"] == "medium"      # list shape, sorted


def test_checkov_empty_output_and_failure(monkeypatch, tmp_path):
    import pytest

    from app.scanners import checkov
    assert checkov.run(tmp_path)["findings"] == []          # no config files -> nothing to run
    (tmp_path / "a.yaml").write_text("kind: Pod")
    monkeypatch.setattr(sandbox, "run", fake_run(stdout="", rc=0))
    assert checkov.run(tmp_path)["findings"] == []
    monkeypatch.setattr(sandbox, "run", fake_run(stdout="", rc=2))
    with pytest.raises(gitleaks.ScannerError):
        checkov.run(tmp_path)


def test_semgrep_maps_severity(monkeypatch, tmp_path):
    from app.scanners import semgrep
    (tmp_path / "rules").mkdir()
    monkeypatch.setattr(semgrep.config, "SEMGREP_RULES", tmp_path / "rules")
    out = json.dumps({"results": [
        {"check_id": "python.lang.security.eval", "path": f"{tmp_path}/a.py", "start": {"line": 2},
         "extra": {"message": "eval is dangerous", "severity": "ERROR"}},
        {"check_id": "x.y.info", "path": f"{tmp_path}/b.js", "start": {"line": 9}, "extra": {"severity": "INFO"}}]})
    monkeypatch.setattr(sandbox, "run", fake_run(stdout=out))
    f = semgrep.run(tmp_path)["findings"]
    assert [x["severity"] for x in f] == ["high", "low"] and f[0]["rule"] == "eval" and f[0]["file"] == "a.py"


def test_semgrep_requires_rules(tmp_path):
    import pytest

    from app.scanners import semgrep
    semgrep.config.SEMGREP_RULES = tmp_path / "missing"
    with pytest.raises(gitleaks.ScannerError):
        semgrep.run(tmp_path)


def test_shellcheck_finds_only_real_scripts(monkeypatch, tmp_path):
    from app.scanners import shellcheck
    (tmp_path / "ok.sh").write_text("echo hi\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.sh").write_text("x\n")
    (tmp_path / "link.sh").symlink_to(tmp_path / "ok.sh")
    assert shellcheck._scripts(tmp_path) == [str(tmp_path / "ok.sh")]
    out = json.dumps([{"file": f"{tmp_path}/ok.sh", "line": 1, "level": "warning", "code": 2086, "message": "Quote it"}])
    monkeypatch.setattr(sandbox, "run", fake_run(stdout=out, rc=1))
    f = shellcheck.run(tmp_path)["findings"]
    assert f == [{"rule": "SC2086", "description": "Quote it", "file": "ok.sh", "line": 1, "severity": "medium"}]
    (tmp_path / "empty").mkdir()
    assert shellcheck.run(tmp_path / "empty")["findings"] == []     # no scripts -> no subprocess


def test_every_scanner_has_meta_and_weight():
    from app.scanners import META, SCANNERS
    from app.scoring import WEIGHTS
    assert {m["key"] for m in META} == set(SCANNERS) == set(WEIGHTS)
