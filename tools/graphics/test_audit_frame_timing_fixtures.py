import sys
from pathlib import Path
sys.path.insert(0, r"staging/integration-probe/python-packages")
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from audit_frame_timing import cfg_reachable, decoded_operand_refs

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = True
md.skipdata = True

# Invalid byte before call eax: skipdata must recover and decode the later call.
fixture = bytes.fromhex("90 0f c3 ff d0 c3")
ins = list(md.disasm(fixture, 0x1000))
assert any(i.id == 0 for i in ins), ins
assert any(i.mnemonic == "call" for i in ins), [(i.mnemonic, i.op_str) for i in ins]
assert all(i.id == 0 or i.operands for i in ins if i.mnemonic == "call")

# CFG: conditional branch includes both fallthrough and target; jmp terminates fallthrough;
# ret terminates blocks. Addresses: 2000 jz 2005, 2002 jmp 2007, 2005 ret, 2007 ret.
fixture = bytes.fromhex("74 03 eb 03 90 c3 90 c3")
base = 0x2000
def byte_at(va, count):
    return fixture[va-base:va-base+count]
reachable, invalid, end = cfg_reachable(base, base, base+len(fixture), byte_at, md, 0x20)
assert {i.address for i in reachable.values()} == {0x2000,0x2002,0x2005,0x2007}, [
    (hex(i.address),i.mnemonic,i.op_str) for i in reachable.values()]
assert not invalid

# Absolute memory operands are captured from structured operands, not byte search.
fixture = bytes.fromhex("a1 88 6f c6 00 c3")
i = next(md.disasm(fixture, 0x3000))
hits = decoded_operand_refs(i, {0x00C66F88:["C66F88"]}, 0x400000)
assert len(hits)==1 and hits[0]["target"]=="C66F88", hits
print("fixtures passed: skipdata recovery, CFG branch edges, absolute-memory operand")
