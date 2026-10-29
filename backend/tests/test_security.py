import os

from app.security import TOKEN_RE, new_token
from app.worker import harden_tree


def test_token_format_and_uniqueness():
    a, b = new_token(), new_token()
    assert TOKEN_RE.match(a) and a != b


def test_harden_tree_removes_symlinks_and_exec_bits(tmp_path):
    (tmp_path / "run.sh").write_text("echo hi")
    os.chmod(tmp_path / "run.sh", 0o4755)
    os.symlink("/etc/passwd", tmp_path / "link")
    harden_tree(tmp_path)
    assert not (tmp_path / "link").exists() and not os.path.islink(tmp_path / "link")
    assert oct((tmp_path / "run.sh").stat().st_mode & 0o7777) == "0o600"
