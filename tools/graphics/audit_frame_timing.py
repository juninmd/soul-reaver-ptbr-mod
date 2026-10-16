import argparse
import hashlib
import json
import sys
from collections import deque
from pathlib import Path

EXPECTED_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
FUNCTION_RVA = 0xAC3E0
MAX_FUNCTION_BYTES = 0x2000
TARGETS = {"C66F3C": 0xC66F3C, "C66F60": 0xC66F60, "C66F64": 0xC66F64,
           "C66F88": 0xC66F88, "QPC": 0x4EC104, "QPF": 0x4EC108, "Sleep": 0x4EC100}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def instruction_record(ins, image_base):
    return {"va": hex(ins.address), "rva": hex(ins.address-image_base),
            "bytes": ins.bytes.hex(), "size": ins.size,
            "mnemonic": ins.mnemonic, "op_str": ins.op_str}


def decoded_operand_refs(ins, target_map, image_base):
    from capstone.x86 import X86_OP_IMM, X86_OP_MEM
    found = []
    for op in getattr(ins, "operands", ()):
        target = None
        kind = None
        if op.type == X86_OP_MEM:
            mem = op.mem
            if mem.base == 0 and mem.index == 0:
                target = mem.disp & 0xFFFFFFFF
                kind = "absolute_memory"
        elif op.type == X86_OP_IMM and ins.mnemonic in ("call", "jmp") or (
                op.type == X86_OP_IMM and ins.mnemonic.startswith("j")):
            target = op.imm & 0xFFFFFFFF
            kind = "control_target"
        if target in target_map:
            for name in target_map[target]:
                found.append({"target": name, "target_va": hex(target),
                              "va": hex(ins.address), "rva": hex(ins.address-image_base),
                              "bytes": ins.bytes.hex(), "mnemonic": ins.mnemonic,
                              "op_str": ins.op_str, "kind": kind})
    return found


def cfg_reachable(start_va, text_start_va, text_end_va, byte_at_va, decoder, max_bytes):
    """Decode only reachable blocks; all branch targets must remain inside .text/window."""
    pending = deque([start_va])
    decoded = {}
    invalid = []
    window_end = min(text_end_va, start_va + max_bytes)
    while pending:
        pc = pending.popleft()
        while text_start_va <= pc < window_end and pc not in decoded:
            chunk = byte_at_va(pc, min(15, window_end-pc))
            ins = next(decoder.disasm(chunk, pc, count=1), None)
            if ins is None or ins.size <= 0 or ins.id == 0:
                invalid.append({"va": hex(pc), "rva": hex(pc - (start_va - FUNCTION_RVA)),
                                "byte": chunk[:1].hex()})
                break
            decoded[pc] = ins
            next_pc = pc + ins.size
            m = ins.mnemonic.lower()
            ops = getattr(ins, "operands", ())
            is_ret = m.startswith("ret") or m in ("iret", "iretd")
            is_uncond = m in ("jmp", "ljmp")
            is_cond = m.startswith("j") and not is_uncond
            if (is_uncond or is_cond) and ops:
                from capstone.x86 import X86_OP_IMM
                if ops[0].type == X86_OP_IMM:
                    target = ops[0].imm & 0xFFFFFFFF
                    if text_start_va <= target < window_end and target not in decoded:
                        pending.append(target)
                if is_uncond:
                    break
            if is_ret:
                break
            # Calls are fallthrough in the current function CFG; callee is not traversed.
            pc = next_pc
    return decoded, invalid, window_end


def main():
    ap = argparse.ArgumentParser(description="Auditoria estática de timing; nunca executa o binário.")
    ap.add_argument("--exe", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--python-packages", type=Path, required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(args.python_packages.resolve()))
    import pefile
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32

    raw = args.exe.read_bytes()
    actual_hash = sha256(raw)
    if actual_hash.lower() != EXPECTED_SHA256:
        raise SystemExit(f"Recusado: SHA-256 inesperado: {actual_hash}")
    pe = pefile.PE(data=raw, fast_load=False)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    md.skipdata = True
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    text_start, text_end = text.VirtualAddress, text.VirtualAddress + min(text.Misc_VirtualSize, text.SizeOfRawData)
    text_file_start = text.PointerToRawData

    def bytes_at_va(va, count):
        rva = va-image_base
        off = text_file_start + (rva-text_start)
        return raw[off:off+count]

    start_va = image_base + FUNCTION_RVA
    cfg, cfg_invalid, cfg_window_end = cfg_reachable(start_va, image_base+text_start,
        image_base+text_end, bytes_at_va, md, MAX_FUNCTION_BYTES)
    if start_va not in cfg:
        raise SystemExit("Capstone não decodificou a instrução inicial da função")
    # Linear xrefs are supplemental and incomplete in code/data mixed sections. Preserve skip-data intervals.
    off = text_file_start
    linear = list(md.disasm(raw[off:off + (text_end-text_start)], image_base+text_start))
    skip_intervals = []
    for ins in linear:
        if ins.id == 0 or ins.mnemonic == ".byte":
            skip_intervals.append({"va_start": hex(ins.address), "va_end_exclusive": hex(ins.address+ins.size),
                                  "bytes": ins.bytes.hex()})
    target_map = {}
    for name, va in TARGETS.items():
        target_map.setdefault(va, []).append(name)
    global_refs = {name: [] for name in TARGETS}
    for ins in linear:
        if ins.id == 0:
            continue
        for hit in decoded_operand_refs(ins, target_map, image_base):
            global_refs[hit["target"]].append(hit)

    fn_refs = []
    direct_callers = []
    for ins in cfg.values():
        fn_refs.extend(decoded_operand_refs(ins, target_map, image_base))
    for ins in linear:
        if ins.id == 0:
            continue
        for hit in decoded_operand_refs(ins, {start_va: ["function_AC3E0"]}, image_base):
            if hit["mnemonic"] == "call":
                direct_callers.append(hit)
    cfg_sorted = sorted(cfg.values(), key=lambda i:i.address)
    end_va = max((i.address+i.size for i in cfg_sorted), default=start_va)
    report = {
        "scope": "static_disassembly_only",
        "input": {"path": str(args.exe.resolve()), "sha256": actual_hash,
                  "expected_sha256": EXPECTED_SHA256, "size_bytes": len(raw)},
        "pe": {"image_base": hex(image_base), "machine": hex(pe.FILE_HEADER.Machine),
               "sections": [{"name": s.Name.rstrip(b"\0").decode("ascii", "replace"),
                             "rva": hex(s.VirtualAddress), "virtual_size": hex(s.Misc_VirtualSize),
                             "raw_size": hex(s.SizeOfRawData)} for s in pe.sections]},
        "function": {"label": "function_at_RVA_AC3E0", "start_va": hex(start_va),
                     "start_rva": hex(FUNCTION_RVA), "cfg_instruction_count": len(cfg),
                     "cfg_max_bytes": hex(MAX_FUNCTION_BYTES), "cfg_window_end_va_exclusive": hex(cfg_window_end),
                     "max_reachable_instruction_end_va": hex(end_va),
                     "boundary_method": "control-flow reachable decode from supplied entry; conditional/unconditional direct branch edges, calls fall through, stop on returns, .text and 0x2000-byte bounds",
                     "invalid_reachable_bytes": cfg_invalid,
                     "instructions": [instruction_record(i,image_base) for i in cfg_sorted],
                     "references": fn_refs},
        "global_references_full_text": {name: {"target_va": hex(TARGETS[name]), "instructions": hits}
                                        for name,hits in global_refs.items()},
        "linear_scan": {"method": "Capstone skipdata=True; only decoded instructions with valid IDs contribute operand references",
                        "skip_data_intervals": skip_intervals,
                        "completeness": "incomplete: linear sweep over mixed code/data may decode data as instructions or skip valid code bytes; CFG is limited to the specified function entry only"},
        "callers_of_function_direct_decoded": direct_callers,
        "interpretation": {"fixed_vs_elapsed": "The supplied function CFG and listed references are static evidence only. QPC/QPF/Sleep use in this CFG is reported by operand; this cannot determine fixed-step versus elapsed-time simulation without tracing relevant data flow and runtime behavior.",
                            "limits": ["Global linear xrefs may be incomplete because .text mixes code and data.",
                                      "Direct xrefs do not reveal indirect calls, executed branches, frequency, or timer conversion semantics.",
                                      "No game executable was launched and no runtime timing measurements were performed."]}
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "cfg_instructions": len(cfg),
                      "function_refs": len(fn_refs), "skip_intervals": len(skip_intervals),
                      "refs": {k:len(v) for k,v in global_refs.items()}, "sha256":actual_hash}))

if __name__ == "__main__":
    main()
