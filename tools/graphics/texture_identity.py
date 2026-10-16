"""Offline identity index for supported 256x256 raw texture pages.

No alpha interpretation, image resizing or game launch is performed. CRC is a
lookup aid; SHA-256 confirms identity and ambiguous pages stay ambiguous.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zlib

HEADER = 4096
SIDE = 256
PAGE = SIDE * SIDE * 2
SUPPORTED = {
    "f287fc2b7452aa3f2592c5bab36654ac8ed2aa1be571e607a31e29a3666868fa": "original-steam",
    "395c403e666825b67033b2f616533e7fd990cdf5f7f02e2e0e1155bb48090554": "mini-mod-STF911",
}


def normalize_rows(data, width, height, row_pitch, bytes_per_pixel=2):
    if any(type(v) is not int or v <= 0 for v in (width, height, row_pitch, bytes_per_pixel)):
        raise ValueError("Invalid upload dimensions/pitch")
    row_bytes = width * bytes_per_pixel
    if row_pitch < row_bytes or len(data) != row_pitch * height:
        raise ValueError("Upload must contain all complete pitched rows")
    return b"".join(data[y * row_pitch:y * row_pitch + row_bytes] for y in range(height))


def digest(data):
    return dict(crc32=f"{zlib.crc32(data):08x}", sha256=hashlib.sha256(data).hexdigest())


def build_index(archive):
    data = Path(archive).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha not in SUPPORTED:
        raise ValueError("Unsupported texture archive SHA-256")
    if len(data) != HEADER + 1287 * PAGE:
        raise ValueError("Invalid fixed-page archive size")
    pages = []
    for index in range(1287):
        page = data[HEADER + index * PAGE:HEADER + (index + 1) * PAGE]
        pages.append(dict(index=index, offset=HEADER + index * PAGE, **digest(page)))
    return dict(schema=1, archive=str(Path(archive).resolve()), archive_sha256=sha,
                variant=SUPPORTED[sha], dimensions=[SIDE, SIDE], bytes_per_pixel=2,
                byte_order="little", format="stored 16-bit words; alpha semantics unverified",
                pages=pages, runtime_verified=False)


def match_upload(index, data, row_pitch, width=256, height=256):
    if (width, height) != (SIDE, SIDE):
        raise ValueError("Only complete 256x256 uploads can identify archive pages")
    identity = digest(normalize_rows(data, width, height, row_pitch))
    matches = [row["index"] for row in index["pages"]
               if row["crc32"] == identity["crc32"] and row["sha256"] == identity["sha256"]]
    return dict(**identity, page_candidates=matches,
                status="unique" if len(matches) == 1 else "ambiguous" if matches else "unmatched",
                interpretation="byte identity only; no UV, alpha or HD replacement proof")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--upload", type=Path)
    parser.add_argument("--row-pitch", type=int, default=512)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() in {p.resolve() for p in (args.archive, args.upload) if p}:
        raise ValueError("Choose a fresh output file outside the input paths")
    result = build_index(args.archive)
    if args.upload:
        result["upload_match"] = match_upload(result, args.upload.read_bytes(), args.row_pitch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(pages=len(result["pages"]), variant=result["variant"],
                          output=str(args.output), runtime_verified=False)))


if __name__ == "__main__":
    main()
