"""Entrypoint inside a scan Job: python -m app.run_scan_job
Reads /work/src (read-only), writes /work/out/result.json. No database, no network."""
import json
import os
from pathlib import Path

from .worker import run_scanners


def main(src: Path = Path("/work/src"), out: Path = Path("/work/out")) -> None:
    names = [n for n in os.getenv("SCAN_SCANNERS", "").split(",") if n]
    results, errors, skipped, timings = run_scanners(names, src)
    tmp = out / "result.json.tmp"
    tmp.write_text(json.dumps({"results": results, "errors": errors, "skipped": skipped, "timings": timings}))
    tmp.rename(out / "result.json")


if __name__ == "__main__":
    main()
