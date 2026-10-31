"""Build a ZIP on the server from individually uploaded files (folder uploads).
Names are client-supplied relative paths, so they are sanitised like any untrusted input."""
import io
import posixpath
import re
import zipfile

_BAD = re.compile(r"[\x00-\x1f\\]")


class BadUpload(ValueError):
    pass


def clean_path(raw: str) -> str | None:
    """Relative POSIX path without '..', drive letters or leading slashes; None = skip entry."""
    p = _BAD.sub("/", raw or "").lstrip("/")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts) or re.match(r"^[A-Za-z]:$", parts[0]):
        return None
    return posixpath.join(*parts)[:400]


def build_zip(items: list[tuple[str, bytes]], max_files: int, max_bytes: int) -> tuple[bytes, str]:
    """items = [(relative_path, content)]. Returns (zip_bytes, display_name)."""
    if len(items) > max_files:
        raise BadUpload(f"too many files (limit {max_files})")
    buf, total, seen = io.BytesIO(), 0, set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for raw, content in items:
            path = clean_path(raw)
            if path is None:
                raise BadUpload("invalid file path")
            total += len(content)
            if total > max_bytes:
                raise BadUpload("upload is too large")
            if path in seen:
                continue
            seen.add(path)
            z.writestr(path, content)
    if not seen:
        raise BadUpload("no files uploaded")
    tops = {p.split("/")[0] for p in seen}
    name = (tops.pop() if len(tops) == 1 and any("/" in p for p in seen) else f"{len(seen)} files")
    return buf.getvalue(), re.sub(r"[^\w.\- ]", "_", name)[:190] + ".zip"
