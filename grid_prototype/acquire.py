"""Restore the exact snapshots listed in data/raw/manifest.json."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-repd", action="store_true")
    args = parser.parse_args()
    raw = Path(__file__).resolve().parent / "data" / "raw"
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    for name, source in manifest.items():
        if name == "repd" and args.without_repd:
            continue
        target = raw / source["file"]
        exists = target.exists()
        if exists:
            data = target.read_bytes()
        else:
            request = Request(source["url"], headers={"User-Agent": "UK-grid-research-prototype/1.0"})
            with urlopen(request, timeout=90) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise SystemExit(f"{target.name}: SHA-256 mismatch; file left untouched.")
        if not exists:
            with target.open("xb") as output:
                output.write(data)
        print(f"{target.name}: verified")


if __name__ == "__main__":
    main()
