import io
import zipfile

import pytest

from app.upload import BadUpload, build_zip, clean_path
from tests.test_api import client  # noqa: F401  (fixture)


@pytest.mark.parametrize("raw,want", [
    ("proj/src/a.py", "proj/src/a.py"), ("/etc/passwd", "etc/passwd"), ("a\\b\\c.txt", "a/b/c.txt"),
    ("./x//y", "x/y"), ("../x", None), ("a/../../x", None), ("C:", None), ("", None),
])
def test_clean_path(raw, want):
    assert clean_path(raw) == want


def test_build_zip_names_and_dedupe():
    data, name = build_zip([("proj/a.py", b"1"), ("proj/b/c.py", b"2"), ("proj/a.py", b"3")], 10, 1000)
    assert name == "proj.zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["proj/a.py", "proj/b/c.py"]
    assert build_zip([("a", b"1"), ("b", b"2")], 10, 1000)[1] == "2 files.zip"


def test_build_zip_limits():
    with pytest.raises(BadUpload):
        build_zip([("a", b"1")] * 3, 2, 100)
    with pytest.raises(BadUpload):
        build_zip([("a", b"x" * 50), ("b", b"x" * 60)], 5, 100)
    with pytest.raises(BadUpload):
        build_zip([("../evil", b"1")], 5, 100)
    with pytest.raises(BadUpload):
        build_zip([], 5, 100)


def test_api_accepts_folder(client):
    r = client.post("/api/v1/scans", data={"scanners": "secrets"},
                    files=[("files", ("proj/a.py", b"print(1)")), ("files", ("proj/sub/b.py", b"x"))])
    assert r.status_code == 202
    assert client.get("/api/v1/scans").json()[0]["filename"] == "proj.zip"


def test_api_rejects_traversal_and_empty(client):
    r = client.post("/api/v1/scans", data={"scanners": "secrets"}, files=[("files", ("../x", b"1"))])
    assert r.status_code == 400
    assert client.post("/api/v1/scans", data={"scanners": "secrets"}).status_code == 400
