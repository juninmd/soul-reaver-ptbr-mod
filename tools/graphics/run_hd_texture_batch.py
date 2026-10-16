"""Resumable full-archive HD texture batch runner.

Wraps `build_hd_texture_pack.build` so the 1.287 pages of the supported
`textures.big` can be processed in chunks instead of a single all-or-nothing
call. Each chunk writes into `out/parts/<first>-<last>`; finished chunks are
skipped on a new run, so an interrupted GPU job resumes where it stopped.

The source archive is only read. Output stays outside the archive directory.
Nothing here proves the runtime loader, UVs, alpha or in-game appearance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_hd_texture_pack import SCALE, SOURCE_SHA256, build  # noqa: E402

TOTAL = 1287


def chunks(pages, size):
    for start in range(0, len(pages), size):
        yield pages[start:start + size]


def part_name(pages):
    return f"{pages[0]:04}-{pages[-1]:04}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--realesrgan", type=Path, required=True)
    parser.add_argument("--model", default="realesrgan-x4plus")
    parser.add_argument("--chunk", type=int, default=64)
    parser.add_argument("--pages", type=int, nargs="*", default=None,
                        help="Explícitas, zero-based. Omitir = 0..1286")
    args = parser.parse_args()

    out = args.out.resolve()
    archive = args.archive.resolve()
    realesrgan = args.realesrgan.resolve()
    if out.is_relative_to(archive.parent) or out in archive.parents:
        raise SystemExit("A saída deve ficar fora do diretório do arquivo-fonte")
    pages = list(range(TOTAL)) if not args.pages else args.pages
    if len(set(pages)) != len(pages) or any(not 0 <= i < TOTAL for i in pages):
        raise SystemExit("Páginas inválidas ou repetidas")
    if args.chunk <= 0:
        raise SystemExit("--chunk precisa ser positivo")
    if not realesrgan.is_file():
        raise SystemExit("Executável RealESRGAN local não encontrado")
    if not archive.is_file():
        raise SystemExit("Arquivo de texturas não encontrado")

    parts_root = out / "parts"
    parts_root.mkdir(parents=True, exist_ok=True)
    total = len(pages)
    done = 0
    for group in chunks(pages, args.chunk):
        name = part_name(group)
        part_dir = parts_root / name
        manifest_path = part_dir / "manifest.json"
        if manifest_path.is_file():
            done += len(group)
            print(json.dumps({"skipped": name, "done": done, "total": total}), flush=True)
            continue
        build(archive, group, part_dir, realesrgan, args.model)
        done += len(group)
        (out / "progress.json").write_text(json.dumps(
            {"schema": 1, "done": done, "total": total, "lastPart": name,
             "sourceArchiveSHA256": SOURCE_SHA256, "runtimeVerified": False},
            indent=2), encoding="utf-8")
        print(json.dumps({"part": name, "done": done, "total": total}), flush=True)

    # Merge part manifests into a single index over the requested pages.
    rows = []
    index = {}
    for group in chunks(pages, args.chunk):
        part_dir = parts_root / part_name(group)
        part = json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))
        for row in part["pages"]:
            rel = Path("parts") / part_name(group) / f"page-{row['id']:04}"
            rows.append(row)
            index[str(row["id"])] = {
                "packedRaw": str((rel / "candidate-argb1555-1024.raw").as_posix()),
                "rgbPng": str((rel / "candidate-rgb-1024.png").as_posix()),
                "original256": str((rel / "original-argb1555-256.raw").as_posix()),
                "originalRgbPng": str((rel / "original-rgb-256.png").as_posix()),
                "bit15Plane": str((rel / "bit15-nearest-1024.raw").as_posix()),
                "sourceRawSHA256": row["sourceRawSHA256"],
                "candidatePackedSHA256": row["candidatePackedSHA256"],
            }
    rows.sort(key=lambda r: r["id"])
    manifest = {
        "schema": 1,
        "sourceArchiveSHA256": SOURCE_SHA256,
        "sourceArchive": str(archive),
        "pagesProcessed": len(rows),
        "pagesTotal": TOTAL,
        "scale": SCALE,
        "model": args.model,
        "chunk": args.chunk,
        "runtimeVerified": False,
        "limitations": [
            "1024x1024 candidate per 256x256 page, not native 4K",
            "no game/runtime validation of loader, UVs or alpha",
            "bit 15 replicated as an uninterpreted plane",
        ],
        "pages": rows,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    (out / "index.json").write_text(json.dumps({"schema": 1, "pages": index}, indent=2),
                                    encoding="utf-8")
    print(json.dumps({"output": str(out), "pages": len(rows), "runtimeVerified": False}))


if __name__ == "__main__":
    main()
