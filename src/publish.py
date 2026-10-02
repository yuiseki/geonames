#!/usr/bin/env python3
"""Push the dated GeoNames snapshots, their Parquet and the card to the Hugging Face Hub.

Each snapshot's files under raw/<YYYYMMDD>/ are GeoNames' own bytes, with
the MANIFEST.json that recorded them, and go up unchanged. A new snapshot is
added beside the others; the ones already on the Hub are not touched, and the
card must declare its four subsets before anything moves.

    uv run python src/publish.py             # dry run
    uv run python src/publish.py --push
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "yuiseki/geonames"
TABLES = {
    "geoname": "geoname/*.parquet",
    "alternate_names": "alternate_names.parquet",
    "hierarchy": "hierarchy.parquet",
    "admin_code5": "admin_code5.parquet",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    data = ROOT / "data"
    card = (data / "README.md").read_text(encoding="utf-8")
    files = ["README.md", "LICENSE", "provenance.yaml"]
    snaps = sorted(p.name for p in (data / "raw").iterdir() if p.is_dir())
    for snap in snaps:
        for table, pattern in TABLES.items():
            if (
                f"- config_name: {snap}.{table}\n  data_files: parquet/{snap}/{pattern}\n"
                not in card
            ):
                raise SystemExit(
                    f"the card does not declare {snap}.{table} at parquet/{snap}/{pattern}"
                )
        manifest = json.loads((data / "raw" / snap / "MANIFEST.json").read_text())
        for name, m in manifest.items():
            if sha256(data / "raw" / snap / name) != m["sha256"]:
                raise SystemExit(f"raw/{snap}/{name} is not the file in its manifest")
        files += [f"raw/{snap}/MANIFEST.json"] + [f"raw/{snap}/{n}" for n in manifest]
        outputs = json.loads((data / "parquet" / snap / "outputs.json").read_text())
        files += [f"parquet/{snap}/outputs.json"] + [f"parquet/{snap}/{n}" for n in outputs]
    print(f"{len(snaps)} snapshots match their manifests: {', '.join(snaps)}")
    total = sum((data / f).stat().st_size for f in files)
    print(f"{a.repo}\n  {len(files)} files, {total / 1e9:.2f} GB")
    if not a.push:
        print("\ndry run. pass --push to upload")
        return 0

    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        folder_path=str(data), repo_id=a.repo, repo_type="dataset", allow_patterns=files
    )
    print(f"\npushed to https://huggingface.co/datasets/{a.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
