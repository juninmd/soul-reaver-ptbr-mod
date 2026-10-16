#!/usr/bin/env python3
"""Offline PE xref audit for wait APIs and timing-related call contexts."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
API_NAMES = ("Sleep", "WaitForSingleObject", "WaitForSingleObjectEx", "WaitForMultipleObjects",
             "GetMessageA", "GetMessageW", "PeekMessageA", "PeekMessageW", "WaitMessage",
             "SetTimer", "QueryPerformanceCounter", "QueryPerformanceFrequency")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--python-packages", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.python_packages.resolve()))
    import pefile
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM

    raw = args.exe.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"refused unexpected exe sha256: {digest}")
    pe = pefile.PE(data=raw)
    base = pe.OPTIONAL_HEADER.ImageBase
    imports = {}
    for desc in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll = desc.dll.decode("ascii", "replace")
        for entry in desc.imports:
            if entry.name:
                name = entry.name.decode("ascii", "replace")
                if name in API_NAMES:
                    imports[name] = {"iat_va": hex(entry.address), "dll": dll}
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    start = base + text.VirtualAddress
    end = start + min(text.Misc_VirtualSize, text.SizeOfRawData)
    raw_start = text.PointerToRawData
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    decoder.skipdata = True
    linear = list(decoder.disasm(raw[raw_start:raw_start + (end-start)], start))
    decoded = [i for i in linear if i.id and i.mnemonic != ".byte"]
    refs = {name: [] for name in imports}
    for index, ins in enumerate(decoded):
        for op in ins.operands:
            target = None
            if op.type == X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                target = op.mem.disp & 0xffffffff
            elif op.type == X86_OP_IMM and ins.mnemonic in ("call", "jmp"):
                target = op.imm & 0xffffffff
            for name, imp in imports.items():
                if target == int(imp["iat_va"], 16):
                    lo, hi = max(0, index-8), min(len(decoded), index+9)
                    refs[name].append({
                        "va": hex(ins.address), "rva": hex(ins.address-base),
                        "bytes": ins.bytes.hex(), "mnemonic": ins.mnemonic, "op_str": ins.op_str,
                        "context_minus8_plus8": [{"va": hex(x.address), "bytes": x.bytes.hex(),
                            "mnemonic": x.mnemonic, "op_str": x.op_str} for x in decoded[lo:hi]]})
    report = {
        "scope": "offline_static_import_xrefs",
        "input": {"path": str(args.exe.resolve()), "sha256": digest, "expected_sha256": EXPECTED_SHA256},
        "scan": {"section": ".text", "method": "Capstone x86-32 skipdata linear sweep; xrefs match absolute IAT operands",
                 "decoded_instruction_count": len(decoded), "skipdata_instruction_count": len(linear)-len(decoded),
                 "context_limit": "8 decoded instructions before and after each hit", "completeness": "bounded/incomplete due mixed code/data and alternate decoding alignments"},
        "imported_wait_and_clock_apis": imports,
        "xrefs": refs,
        "non_imported_presentation_apis": {"DirectDrawSurface_Flip": "COM vtable call; no direct import xref expected",
            "IDirectDraw_WaitForVerticalBlank": "COM vtable call; no direct import xref expected",
            "limits": "This audit does not infer COM interface slots or prove presentation behavior."},
        "execution": {"game_launched": False, "process_attached": False}
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "imports": len(imports),
                      "hits": {k: len(v) for k, v in refs.items()}, "sha256": digest}))


if __name__ == "__main__":
    main()
