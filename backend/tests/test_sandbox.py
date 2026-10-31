import subprocess
import time

import pytest

from app import sandbox


def test_secrets_not_inherited(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/x")
    monkeypatch.setenv("REDIS_PASSWORD", "hunter2")
    out = sandbox.run(["env"], 10, {"FOO": "bar"}).stdout
    assert "DATABASE_URL" not in out and "REDIS" not in out and "hunter2" not in out
    assert "FOO=bar" in out and "HOME=/tmp" in out


def test_timeout_kills_whole_tree(tmp_path):
    marker = tmp_path / "alive"
    t = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        sandbox.run(["sh", "-c", f"(sleep 3; touch {marker}) & sleep 30"], 1)
    time.sleep(3.5)
    assert not marker.exists() and time.time() - t < 8


def test_missing_binary_and_exit_code():
    with pytest.raises(FileNotFoundError):
        sandbox.run(["definitely-not-a-binary"], 5)
    assert sandbox.run(["sh", "-c", "echo hi; exit 3"], 5).returncode == 3


def test_file_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "FSIZE", 1024 * 1024)
    r = sandbox.run(["sh", "-c", f"head -c 5000000 /dev/zero > {tmp_path}/big"], 10)
    assert r.returncode != 0 and (tmp_path / "big").stat().st_size <= 1024 * 1024
