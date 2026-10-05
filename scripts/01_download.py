#!/usr/bin/env python3
"""Fetch today's GeoNames dump, or adopt one fetched earlier, as a dated snapshot.

GeoNames (https://download.geonames.org/export/dump/) rebuilds its dump every
night at the same URLs, with no version number or checksum; past versions are
kept only for paying subscribers. Each snapshot here is one night's files,
unchanged, under data/raw/<YYYYMMDD>/, named after the UTC day of
allCountries.zip's Last-Modified. A new snapshot is added beside the others.

Taken: the gazetteer (allCountries.zip), the alternate names
(alternateNamesV2.zip), the hierarchy, the fifth admin level, the small code
tables and readme.txt. The per-country zips and the cities files are subsets
of allCountries and are not taken; nor is the obsolete alternateNames.zip.

The server is slow (70 to 140 KB/s on 2026-10-01; allCountries.zip took about
50 minutes). A cut download resumes with If-Range, so a file that changed
meanwhile comes back whole. The Last-Modified of every file is read before
and after; if any moved, the run stops.

    uv run python scripts/01_download.py                         # tonight's dump
    uv run python scripts/01_download.py --from /sata_hdd_24tb/www/html/static/geonames/2026-10-01

--from adopts a snapshot fetched earlier by study-geoai-algo-py's
mirror_geonames.py: its raw/ files are copied only if each has the size and
sha256 its manifest.json recorded when it was fetched.
"""

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw"
BASE = "https://download.geonames.org/export/dump/"
UA = "geonames-snapshots/1 (+https://github.com/yuiseki/geonames)"
FILES = [
    "allCountries.zip", "alternateNamesV2.zip", "hierarchy.zip", "adminCode5.zip",
    "admin1CodesASCII.txt", "admin2Codes.txt", "countryInfo.txt", "featureCodes_en.txt",
    "iso-languagecodes.txt", "timeZones.txt", "readme.txt",
]  # fmt: skip

# columns as readme.txt lists them, in snake case


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def snapshot_name(last_modified: str) -> str:
    """The UTC day of a Last-Modified header, as YYYYMMDD."""
    return email.utils.parsedate_to_datetime(last_modified).astimezone(dt.UTC).strftime("%Y%m%d")


def head(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {
            "last_modified": r.headers["Last-Modified"],
            "bytes": int(r.headers["Content-Length"]),
        }


def fetch(url: str, dest: Path, meta: dict) -> None:
    """Download url to dest, resuming a partial file only while it is the same version.

    The server is slow (about 70 KB/s on 2026-10-01), so a cut connection is
    resumed with If-Range: a changed file comes back whole with 200.
    """
    if dest.exists() and dest.stat().st_size == meta["bytes"]:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(20):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"User-Agent": UA}
        if have:
            headers |= {"Range": f"bytes={have}-", "If-Range": meta["last_modified"]}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as r:
                mode = "ab" if r.status == 206 else "wb"
                with open(tmp, mode) as f:
                    shutil.copyfileobj(r, f, 1 << 20)
            break
        except (OSError, urllib.error.URLError) as e:
            log(f"retry {dest.name} at {have:,} bytes: {e}")
            time.sleep(min(60, 5 * (attempt + 1)))
    else:
        raise RuntimeError(f"{dest.name}: gave up")
    if tmp.stat().st_size != meta["bytes"]:
        raise RuntimeError(f"{dest.name}: got {tmp.stat().st_size} bytes, listed {meta['bytes']}")
    tmp.replace(dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def adopt(src: Path, out: Path, files: list[str] = FILES) -> Path:
    """Copy a snapshot fetched earlier, file by file against the sha256 it recorded."""
    sources = json.loads((src / "manifest.json").read_text())["sources"]
    snap = out / snapshot_name(sources["allCountries.zip"]["last_modified"])
    snap.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in files:
        s = sources[name]
        p = src / "raw" / name
        if p.stat().st_size != s["bytes"] or sha256(p) != s["sha256"]:
            raise SystemExit(f"{p} is not the file its manifest recorded")
        tmp = snap / (name + ".part")
        shutil.copyfile(p, tmp)
        tmp.replace(snap / name)
        manifest[name] = {k: s[k] for k in ("url", "bytes", "sha256", "last_modified")}
    (snap / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    return snap


def download(out: Path) -> Path:
    before = {f: head(BASE + f) for f in FILES}
    snap = out / snapshot_name(before["allCountries.zip"]["last_modified"])
    if (snap / "MANIFEST.json").exists():
        log(f"{snap.name} is already here")
        return snap
    snap.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        fetch(BASE + f, snap / f, before[f])
        log(f"have {f}")
    after = {f: head(BASE + f) for f in FILES}
    moved = [f for f in FILES if after[f] != before[f]]
    if moved:
        raise SystemExit(f"changed upstream while downloading: {moved}; run again")
    manifest = {
        f: {"url": BASE + f, "bytes": before[f]["bytes"], "sha256": sha256(snap / f),
             "last_modified": before[f]["last_modified"]}
        for f in FILES
    }  # fmt: skip
    (snap / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    return snap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", type=Path, help="adopt a snapshot fetched earlier")
    a = ap.parse_args()
    snap = adopt(a.src, OUT) if a.src else download(OUT)
    log(f"snapshot {snap.name}: {len(json.loads((snap / 'MANIFEST.json').read_text()))} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
