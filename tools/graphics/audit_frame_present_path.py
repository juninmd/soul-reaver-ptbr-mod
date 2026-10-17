#!/usr/bin/env python3
"""Varredura estática de xrefs de timing e candidatos DirectDraw Flip.

O script apenas lê uma cópia PE identificada por SHA-256. A varredura linear
com Capstone é auxiliar: não resolve chamadas COM/vtable nem prova execução.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
TIMING_GLOBALS = {
    "step_flag_C66F80": 0x00C66F80,
    "step_counter_C66E50": 0x00C66E50,
    "step_accumulator_C66F84": 0x00C66F84,
}
DIRECT_TARGETS = {
    "integrator_4AC3E0": 0x004AC3E0,
    "outer_update_4AC540": 0x004AC540,
    "top_state_wrapper_4ACFC0": 0x004ACFC0,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python-packages", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.python_packages.resolve()))
    import pefile
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM

    raw = args.exe.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"Recusado: SHA-256 inesperado: {digest}")
    pe = pefile.PE(data=raw, fast_load=False)
    base = pe.OPTIONAL_HEADER.ImageBase
    text = next(section for section in pe.sections if section.Name.rstrip(b"\0") == b".text")
    text_rva = text.VirtualAddress
    text_size = min(text.Misc_VirtualSize, text.SizeOfRawData)
    text_va = base + text_rva
    code = raw[text.PointerToRawData:text.PointerToRawData + text_size]

    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True
    decoder.skipdata = True
    rows = list(decoder.disasm(code, text_va))
    decoded = [ins for ins in rows if ins.id and ins.mnemonic != ".byte"]
    target_to_global = {address: name for name, address in TIMING_GLOBALS.items()}
    target_to_func = {address: name for name, address in DIRECT_TARGETS.items()}
    global_xrefs = {name: [] for name in TIMING_GLOBALS}
    direct_calls = {name: [] for name in DIRECT_TARGETS}
    flip_slot_calls = []
    indirect_calls = []
    indirect_disp_histogram: dict[str, int] = {}
    surface_method_slot_candidates = {"Blt_0x14": [], "BltFast_0x1c": [], "Flip_0x2c": []}

    for index, ins in enumerate(decoded):
        for operand in ins.operands:
            if operand.type == X86_OP_MEM:
                mem = operand.mem
                if mem.base == 0 and mem.index == 0:
                    address = mem.disp & 0xFFFFFFFF
                    if address in target_to_global:
                        name = target_to_global[address]
                        global_xrefs[name].append({
                            "va": hex(ins.address), "rva": hex(ins.address - base),
                            "bytes": ins.bytes.hex(), "mnemonic": ins.mnemonic,
                            "op_str": ins.op_str,
                        })
                if ins.mnemonic == "call":
                    record = {
                        "va": hex(ins.address), "rva": hex(ins.address - base),
                        "bytes": ins.bytes.hex(), "op_str": ins.op_str,
                        "base_register": ins.reg_name(mem.base) if mem.base else None,
                        "index_register": ins.reg_name(mem.index) if mem.index else None,
                        "displacement": hex(mem.disp & 0xFFFFFFFF),
                    }
                    indirect_calls.append(record)
                    displacement = hex(mem.disp & 0xFFFFFFFF)
                    indirect_disp_histogram[displacement] = indirect_disp_histogram.get(displacement, 0) + 1
                    slot_names = {0x14: "Blt_0x14", 0x1C: "BltFast_0x1c", 0x2C: "Flip_0x2c"}
                    if mem.base != 0 and mem.index == 0 and mem.disp in slot_names:
                        lo, hi = max(0, index - 5), min(len(decoded), index + 6)
                        candidate = {
                            **record,
                            "context": [{"va": hex(item.address), "bytes": item.bytes.hex(),
                                         "mnemonic": item.mnemonic, "op_str": item.op_str}
                                        for item in decoded[lo:hi]],
                        }
                        surface_method_slot_candidates[slot_names[mem.disp]].append(candidate)
                    # IDirectDrawSurface::Flip is slot 11 (byte displacement 0x2c)
                    # in the classic interface. This is a candidate signature only.
                    if mem.base != 0 and mem.index == 0 and mem.disp == 0x2C:
                        flip_slot_calls.append(candidate)
            elif operand.type == X86_OP_IMM and ins.mnemonic == "call":
                target = operand.imm & 0xFFFFFFFF
                if target in target_to_func:
                    direct_calls[target_to_func[target]].append({
                        "va": hex(ins.address), "rva": hex(ins.address - base),
                        "bytes": ins.bytes.hex(), "target": hex(target),
                    })

    report = {
        "scope": "static_only_no_execution",
        "input": {"path": str(args.exe.resolve()), "sha256": digest,
                  "expected_sha256": EXPECTED_SHA256, "size_bytes": len(raw)},
        "scan": {"section": ".text", "rva": hex(text_rva), "size": hex(text_size),
                 "method": "Capstone x86-32 linear sweep, skipdata enabled",
                 "decoded_instructions": len(decoded),
                 "skipped_data_items": len(rows) - len(decoded),
                 "limitation": "seções podem misturar código/dados; xrefs e candidatos podem faltar ou incluir falsos positivos"},
        "timing_global_xrefs": global_xrefs,
        "direct_call_xrefs": direct_calls,
        "com_indirect_calls": {
            "total_call_mem_operands": len(indirect_calls),
            "displacement_histogram": indirect_disp_histogram,
            "surface_method_slot_candidates": surface_method_slot_candidates,
            "surface_flip_slot_0x2c_candidates": flip_slot_calls,
            "interpretation": "0x2c é o slot Flip clássico de IDirectDrawSurface; sem proveniência do objeto/vtable e do fluxo de controle, candidatos não confirmam Flip nem Present",
        },
        "execution": {"game_launched": False, "process_attached": False,
                      "game_or_steam_files_modified": False},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": digest,
                      "decoded_instructions": len(decoded),
                      "timing_xrefs": {key: len(value) for key, value in global_xrefs.items()},
                      "direct_call_xrefs": {key: len(value) for key, value in direct_calls.items()},
                      "indirect_calls": len(indirect_calls),
                      "slot_candidates": {key: len(value) for key, value in surface_method_slot_candidates.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
