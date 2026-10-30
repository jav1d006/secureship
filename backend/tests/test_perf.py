"""Speed-ups: parallel scanners, skipping irrelevant ones, one shared `trivy config` run."""
import time

import pytest

from app import worker
from app.scanners import detect, trivy_config


def make(tmp_path, *files):
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return detect.inventory(tmp_path)


def test_irrelevant_scanners_are_skipped(tmp_path):
    inv = make(tmp_path, "README.md", "notes.txt")
    for k in ("dependencies", "code", "semgrep", "iac", "checkov", "docker", "shell"):
        assert detect.skip_reason(k, inv), k
    assert detect.skip_reason("secrets", inv) is None            # secrets are always scanned


def test_relevant_scanners_run(tmp_path):
    inv = make(tmp_path, "app/main.py", "requirements.txt", "Dockerfile", "k8s/a.yaml", "run.sh", "main.tf")
    for k in ("dependencies", "code", "semgrep", "iac", "checkov", "docker", "shell", "secrets"):
        assert detect.skip_reason(k, inv) is None, k


def test_node_modules_and_git_are_ignored(tmp_path):
    inv = make(tmp_path, "node_modules/x/index.py", ".git/hooks/pre.sh", "vendor/a.go")
    assert not inv.paths and detect.skip_reason("code", inv) and detect.skip_reason("shell", inv)


def test_checkov_frameworks_follow_the_project(tmp_path):
    assert detect.checkov_frameworks(make(tmp_path, "main.tf")) == "terraform"
    assert detect.checkov_frameworks(make(tmp_path, "Dockerfile")) == "terraform,dockerfile"   # tmp_path is shared
    inv = detect.inventory(tmp_path)
    assert "terraform" in detect.checkov_frameworks(inv)


def test_checkov_frameworks_github_actions_and_k8s(tmp_path):
    fw = detect.checkov_frameworks(make(tmp_path, ".github/workflows/ci.yml", "k8s/a.yaml")).split(",")
    assert {"kubernetes", "cloudformation", "github_actions"} <= set(fw) and "terraform" not in fw


@pytest.fixture
def fake_scanners(monkeypatch):
    calls = []

    def slow(name):
        def fn(path):
            calls.append(name)
            time.sleep(0.4)
            return {"findings": [{"severity": "low"}]}
        return fn

    def boom(path):
        raise RuntimeError("tool crashed")

    reg = {"semgrep": slow("semgrep"), "checkov": slow("checkov"), "code": slow("code"),
           "docker": slow("docker"), "secrets": boom}
    monkeypatch.setattr(worker, "SCANNERS", reg)
    monkeypatch.setattr(worker, "TAKES_INVENTORY", set())
    return calls


def test_scanners_run_in_parallel_and_failures_are_isolated(tmp_path, fake_scanners):
    make(tmp_path, "a.py", "k8s/a.yaml")
    t = time.perf_counter()
    results, errors, skipped, timings = worker.run_scanners(["semgrep", "code", "secrets", "docker"], tmp_path)
    assert time.perf_counter() - t < 0.7                         # semgrep and code overlapped (sequential = 0.8s+)
    assert set(results) == {"semgrep", "code"} and set(errors) == {"secrets"}
    assert "docker" in skipped and "docker" not in results
    assert set(timings) == {"semgrep", "code", "secrets"}


def test_heavy_scanners_are_gated_one_at_a_time(tmp_path, fake_scanners):
    make(tmp_path, "a.py", "k8s/a.yaml")
    t = time.perf_counter()
    worker.run_scanners(["semgrep", "checkov"], tmp_path)       # same "heavy" group -> serialised
    assert time.perf_counter() - t >= 0.75


def test_unknown_and_duplicate_scanner_names_are_ignored(tmp_path, fake_scanners):
    make(tmp_path, "a.py")
    results, *_ = worker.run_scanners(["code", "code", "nope"], tmp_path)
    assert list(results) == ["code"] and fake_scanners.count("code") == 1


def test_trivy_config_runs_once_for_iac_and_docker(tmp_path, monkeypatch):
    n = []
    monkeypatch.setattr(trivy_config, "_memo", {})
    monkeypatch.setattr(trivy_config, "_scan_uncached",
                        lambda p: n.append(1) or [{"rule": "X", "description": "d", "file": "f", "line": 1,
                                                   "severity": "low", "_docker": True}])
    assert len(trivy_config.run_docker(tmp_path)["findings"]) == 1
    assert trivy_config.run_iac(tmp_path)["findings"] == []
    assert len(n) == 1
