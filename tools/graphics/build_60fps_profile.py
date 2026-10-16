#!/usr/bin/env python3
"""Build an isolated dgVoodoo 60 Hz presentation candidate; never edits its input."""
from __future__ import annotations

import argparse
import configparser
from pathlib import Path


def update_config(source: Path, destination: Path) -> dict[str, object]:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if source_resolved == destination_resolved:
        raise ValueError("refusing output equal to source")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {destination}")
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=("="))
    parser.optionxform = str.lower
    parser.read_string("[__global__]\n" + text)
    required = {"generalext": {"fpslimit"}, "directx": {"forceverticalsync"}}
    sections = {}
    for name in parser.sections():
        normalized = name.lower()
        if normalized in sections:
            raise ValueError(f"duplicate section [{name}]")
        sections[normalized] = name
    for section, keys in required.items():
        if section not in sections:
            raise ValueError(f"missing section [{section}]")
        for key in keys:
            if not parser.has_option(sections[section], key):
                raise ValueError(f"missing key {key} in [{section}]")

    # Preserve the source formatting and alter only the two verified entries.
    lines = text.splitlines(keepends=True)
    section = ""
    seen: dict[tuple[str, str], int] = {}
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
        if stripped and not stripped.startswith((";", "#")) and "=" in line:
            key, _ = line.split("=", 1)
            normalized = key.strip().lower()
            target = (section, normalized)
            if target in (("generalext", "fpslimit"), ("directx", "forceverticalsync")):
                seen[target] = seen.get(target, 0) + 1
                value = "60" if target == ("generalext", "fpslimit") else "false"
                line = f"{key.rstrip()} = {value}" + ("\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "")
        output.append(line)
    expected = {("generalext", "fpslimit"), ("directx", "forceverticalsync")}
    if set(seen) != expected:
        raise ValueError("required setting is absent or duplicated")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write("".join(output).encode("utf-8"))
    return {"source_bytes": len(raw), "candidate_bytes": destination.stat().st_size,
            "changed_keys": {"GeneralExt.FPSLimit": "60", "DirectX.ForceVerticalSync": "false"}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"source config not found: {args.source}")
    try:
        metadata = update_config(args.source, args.output)
    except (ValueError, FileExistsError) as exc:
        raise SystemExit(str(exc)) from exc
    print(metadata)


if __name__ == "__main__":
    main()
