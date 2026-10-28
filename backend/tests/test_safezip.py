import zipfile

import pytest

from app.safezip import UnsafeArchive, safe_extract


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_extracts_normal_archive(tmp_path):
    z = tmp_path / "a.zip"
    _zip(z, {"src/app.py": "print(1)", "README.md": "hi"})
    n = safe_extract(z, tmp_path / "out", max_bytes=10_000, max_files=10)
    assert n == 2
    assert (tmp_path / "out" / "src" / "app.py").read_text() == "print(1)"


def test_blocks_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    _zip(z, {"../../escape.txt": "x"})
    with pytest.raises(UnsafeArchive):
        safe_extract(z, tmp_path / "out", max_bytes=10_000, max_files=10)
    assert not (tmp_path / "escape.txt").exists()


def test_blocks_zip_bomb_and_file_count(tmp_path):
    z = tmp_path / "big.zip"
    _zip(z, {"a": "0" * 5000, "b": "0" * 5000})
    with pytest.raises(UnsafeArchive):
        safe_extract(z, tmp_path / "o1", max_bytes=1000, max_files=10)
    with pytest.raises(UnsafeArchive):
        safe_extract(z, tmp_path / "o2", max_bytes=10**6, max_files=1)


def test_rejects_non_zip(tmp_path):
    f = tmp_path / "x.zip"
    f.write_text("not a zip")
    with pytest.raises(UnsafeArchive):
        safe_extract(f, tmp_path / "out", max_bytes=1000, max_files=10)
