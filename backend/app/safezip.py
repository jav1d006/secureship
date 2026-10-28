"""Safe ZIP extraction. Uploaded archives are untrusted: we only ever write
regular files under the target directory and never execute anything."""
import stat
import zipfile
from pathlib import Path


class UnsafeArchive(Exception):
    pass


def safe_extract(zip_path: Path, dest: Path, max_bytes: int, max_files: int) -> int:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise UnsafeArchive("not a valid zip file") from e

    with zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise UnsafeArchive(f"too many entries (limit {max_files})")
        # Check declared sizes up front (cheap), enforce real sizes while copying.
        if sum(i.file_size for i in infos) > max_bytes:
            raise UnsafeArchive("archive expands beyond the size limit")

        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                continue  # skip symlinks entirely
            target = (dest / info.filename).resolve()
            if dest != target and dest not in target.parents:
                raise UnsafeArchive("path traversal detected")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            count += 1
            with zf.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise UnsafeArchive("archive expands beyond the size limit")
                    out.write(chunk)
            target.chmod(0o644)  # never keep an executable bit
    return count
