"""Pins the kain2.exe bytes that startup_patches.h expects (skipped without the game)."""
import os
import struct
import unittest
from pathlib import Path

EXE = Path(os.environ.get("SR_GAME_DIR", r"D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver")) / "kain2.exe"
IMAGE_BASE = 0x400000


def file_offset(data, va):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections = struct.unpack_from("<H", data, pe + 6)[0]
    opt = struct.unpack_from("<H", data, pe + 20)[0]
    first = pe + 24 + opt
    for i in range(sections):
        _, vsize, vaddr, rawsize, rawptr = struct.unpack_from("<8sIIII", data, first + i * 40)
        rel = va - IMAGE_BASE - vaddr
        if 0 <= rel < rawsize:
            return rawptr + rel
    raise ValueError(hex(va))


@unittest.skipUnless(EXE.is_file(), "kain2.exe not available")
class StartupPatchBytes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = EXE.read_bytes()

    def at(self, va, size):
        off = file_offset(self.data, va)
        return self.data[off:off + size]

    def test_intro_chain_publogo_then_crylogo_then_legal(self):
        # entry 0 -> next 1 (crylogo); patch retargets to 5 (legal.pti, "press enter")
        self.assertEqual(self.at(0x4F44A8, 11), b"publogo.rpl")
        self.assertEqual(self.at(0x4F44DE, 2), b"\x01\x00")
        self.assertEqual(self.at(0x4F44E0, 11), b"crylogo.rpl")
        self.assertEqual(self.at(0x4F45C0, 6), b"\kain2")
        self.assertEqual(self.at(0x4F45C0 + 0x36, 2), b"\xff\xff")

    def test_setup_dialog_call_is_the_only_dialogbox(self):
        self.assertEqual(self.at(0x47AF10, 6), b"\xff\x15\x1c\xc2\x4e\x00")

    def test_fmv_player_prologue_for_trampoline(self):
        # fmv_trace.h copies these 6 bytes (sub esp, 0x140) into its trampoline
        self.assertEqual(self.at(0x47D920, 6), b"\x81\xec\x40\x01\x00\x00")

    def test_hd_texture_hook_sites(self):
        # hd_textures.h: both page surfaces are created 0x100 wide/high (mov eax, 0x100) and 0x472E70 is the uploader
        self.assertEqual(self.at(0x472C21, 5), b"\xb8\x00\x01\x00\x00")
        self.assertEqual(self.at(0x472D31, 5), b"\xb8\x00\x01\x00\x00")
        self.assertEqual(self.at(0x472E70, 6), b"\x81\xec\x88\x00\x00\x00")
        self.assertEqual(struct.unpack("<f", self.at(0x4EC378, 4))[0], 1 / 4096)  # normalized UV scale


if __name__ == "__main__":
    unittest.main()
