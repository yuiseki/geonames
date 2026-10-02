import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "download", Path(__file__).parents[1] / "scripts" / "01_download.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


@pytest.mark.parametrize(
    ("last_modified", "name"),
    [
        ("Thu, 01 Oct 2026 02:08:51 GMT", "20261001"),
        # GeoNames rebuilds around 02:00 GMT; the snapshot is the UTC day
        ("Wed, 30 Sep 2026 23:59:59 GMT", "20260930"),
    ],
)
def test_snapshot_name_is_the_utc_day(last_modified, name):
    assert m.snapshot_name(last_modified) == name


def test_adopt_copies_files_that_match_their_manifest(tmp_path):
    src = tmp_path / "mirror"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "readme.txt").write_bytes(b"readme")
    (src / "raw" / "allCountries.zip").write_bytes(b"zip")
    import hashlib

    def entry(b):
        return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                "last_modified": "Thu, 01 Oct 2026 02:08:51 GMT", "url": "u"}  # fmt: skip

    (src / "manifest.json").write_text(json.dumps({"sources": {
        "readme.txt": entry(b"readme"), "allCountries.zip": entry(b"zip")}}))  # fmt: skip
    out = tmp_path / "raw"
    snap = m.adopt(src, out, files=["readme.txt", "allCountries.zip"])
    assert snap == out / "20261001"
    assert (snap / "readme.txt").read_bytes() == b"readme"
    manifest = json.loads((snap / "MANIFEST.json").read_text())
    assert manifest["allCountries.zip"]["sha256"] == entry(b"zip")["sha256"]


def test_adopt_refuses_a_file_that_differs(tmp_path):
    src = tmp_path / "mirror"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "allCountries.zip").write_bytes(b"changed")
    (src / "manifest.json").write_text(json.dumps({"sources": {"allCountries.zip": {
        "bytes": 3, "sha256": "0" * 64, "last_modified": "Thu, 01 Oct 2026 02:08:51 GMT", "url": "u"}}}))  # fmt: skip
    with pytest.raises(SystemExit, match="not the file"):
        m.adopt(src, tmp_path / "raw", files=["allCountries.zip"])
    assert not (tmp_path / "raw" / "20261001" / "allCountries.zip").exists()
