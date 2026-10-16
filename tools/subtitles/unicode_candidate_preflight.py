#!/usr/bin/env python3
"""Read-only structural preflight for an isolated Unicode subtitle candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import unicodedata
from pathlib import Path

EXPECTED_EXE_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
EXPECTED_VOICES_SHA256 = "92e9a4fd2b262cdd8922b1f96cd3e098c730169add761bf0cc4e6844baacdb88"
EXPECTED_CAPTIONS_SHA256 = "4046aa9dc8a79504d61c3b1a805972ccc96265de95ad3fbbaf8bfc79e341dd08"
CAPTION_COUNT = 230


def find_repo_root(start: Path | None = None) -> Path:
    for candidate in (start or Path(__file__).resolve()).resolve().parents:
        if (candidate / "AGENTS.md").is_file() and (candidate / "Cargo.toml").is_file():
            return candidate
    raise RuntimeError("não foi possível localizar a raiz do repositório (AGENTS.md + Cargo.toml)")


ROOT = find_repo_root()


class PreflightError(ValueError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def _inside_staging(game: Path) -> None:
    staging = (ROOT / "staging").resolve()
    resolved = game.resolve(strict=True)
    _require(resolved != staging and staging in resolved.parents,
             "--game precisa estar dentro de repo/staging (cópia isolada), nunca na instalação original")


def _pe_x86(path: Path, label: str | None = None) -> None:
    label = label or path.name
    data = path.read_bytes()
    _require(len(data) >= 64 and data[:2] == b"MZ", f"{label} não tem cabeçalho MZ válido")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    _require(pe_offset + 24 <= len(data) and data[pe_offset:pe_offset + 4] == b"PE\0\0",
             f"{label} não tem cabeçalho PE/COFF completo")
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    _require(machine == 0x14C, f"{label} precisa ser PE x86 (Machine=0x14c), encontrado 0x{machine:04x}")
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_start = pe_offset + 24
    _require(optional_size >= 2 and optional_start + optional_size <= len(data),
             f"{label} tem SizeOfOptionalHeader inválido ou truncado")
    optional_magic = struct.unpack_from("<H", data, optional_start)[0]
    _require(optional_magic == 0x10B,
             f"{label} precisa ter Optional Header PE32 x86 (Magic=0x10b), encontrado 0x{optional_magic:04x}")


def _config(path: Path) -> None:
    raw = path.read_text(encoding="utf-8-sig", errors="strict")
    values: dict[str, list[str]] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values.setdefault(key.strip().casefold(), []).append(value.strip())
    _require(values.get("fullscreenmode") == ["false"], "dgVoodoo.conf precisa definir FullScreenMode=false uma única vez")
    resolutions = values.get("resolution", [])
    _require(bool(resolutions) and all(re.fullmatch(r"h\s*:\s*3840\s*,\s*v\s*:\s*2160", v, re.I) for v in resolutions),
             "dgVoodoo.conf precisa ter Resolution h:3840, v:2160 em todas as ocorrências")


def _no_controls(text: str, where: str) -> None:
    _require(not any(unicodedata.category(ch) in {"Cc", "Cf", "Cn", "Co", "Cs"} for ch in text),
             f"{where} contém caracteres Unicode de categoria Cc/Cf/Cn/Co/Cs")


def _captions(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"captions JSON inválido em UTF-8: {exc}") from exc
    _require(isinstance(data, dict), "captions deve ser objeto JSON")
    for key, expected in (("schema", 1), ("format", "unicode-v1"), ("encoding", "UTF-8"),
                          ("normalization", "NFC"), ("namespace", "voices.dat")):
        _require(data.get(key) == expected, f"captions.{key} deve ser {expected!r}")
    rows = data.get("captions")
    _require(isinstance(rows, list) and len(rows) == CAPTION_COUNT,
             f"esperadas exatamente {CAPTION_COUNT} captions; recebido {len(rows) if isinstance(rows, list) else 'tipo inválido'}")
    ids: set[int] = set()
    for index, row in enumerate(rows):
        where = f"captions[{index}]"
        _require(isinstance(row, dict), f"{where} deve ser objeto")
        caption_id, duration, text = row.get("id"), row.get("duration_ms"), row.get("text")
        _require(type(caption_id) is int and 0 <= caption_id <= 478, f"{where}.id precisa ser inteiro entre 0 e 478")
        _require(caption_id not in ids, f"id duplicado: {caption_id}")
        ids.add(caption_id)
        _require(type(duration) is int and 100 <= duration <= 60000, f"{where}.duration_ms fora de 100..60000")
        _require(isinstance(text, str) and text.strip() != "", f"{where}.text precisa ser texto não vazio após strip")
        _require(unicodedata.is_normalized("NFC", text), f"{where}.text não está em NFC")
        _no_controls(text, f"{where}.text")
        _require(len(text) <= 4000, f"{where}.text excede 4000 caracteres")
        _require(len(text.encode("utf-8")) <= 16000, f"{where}.text excede 16000 bytes UTF-8")
        pages = row.get("pages")
        _require(isinstance(pages, list) and pages, f"{where}.pages precisa ser lista não vazia")
        cursor = 0
        page_texts = []
        for page_index, page in enumerate(pages):
            pwhere = f"{where}.pages[{page_index}]"
            _require(isinstance(page, dict), f"{pwhere} deve ser objeto")
            ptext, start, end = page.get("text"), page.get("start_ms"), page.get("end_ms")
            _require(isinstance(ptext, str) and ptext.strip() != "", f"{pwhere}.text precisa ser texto não vazio após strip")
            _require(unicodedata.is_normalized("NFC", ptext), f"{pwhere}.text não está em NFC")
            _no_controls(ptext, f"{pwhere}.text")
            _require(len(ptext) <= 4000, f"{pwhere}.text excede 4000 caracteres")
            _require(len(ptext.encode("utf-8")) <= 16000, f"{pwhere}.text excede 16000 bytes UTF-8")
            _require(type(start) is int and type(end) is int and start == cursor and end > start and end <= duration,
                     f"{pwhere} precisa ser contígua, positiva e terminar até duration_ms")
            cursor = end
            page_texts.append(ptext)
        _require(cursor == duration, f"{where}: páginas não cobrem toda a duração")
        joined = unicodedata.normalize("NFC", " ".join(" ".join(page_texts).split()))
        normalized = unicodedata.normalize("NFC", " ".join(text.split()))
        _require(joined == normalized, f"{where}: concatenação normalizada das páginas difere do texto original")


def preflight(game: Path, overlay: Path, captions: Path) -> dict:
    game, overlay, captions = Path(game), Path(overlay), Path(captions)
    _inside_staging(game)
    _require(game.is_dir(), "--game precisa ser diretório")
    _require(not (game / "DINPUT.dll").exists(), "DINPUT.dll ativo é recusado: pode ativar proxy de legenda ASCII")
    required = ("kain2.exe", "voices.dat", "DDraw.dll", "D3DImm.dll", "dgVoodoo.conf")
    missing = [name for name in required if not (game / name).is_file()]
    _require(not missing, "arquivos obrigatórios ausentes: " + ", ".join(missing))
    exe_sha = sha256(game / "kain2.exe")
    voices_sha = sha256(game / "voices.dat")
    _require(exe_sha == EXPECTED_EXE_SHA256, f"SHA-256 de kain2.exe divergente: {exe_sha}")
    _require(voices_sha == EXPECTED_VOICES_SHA256, f"SHA-256 de voices.dat divergente: {voices_sha}")
    _pe_x86(game / "kain2.exe", "kain2.exe")
    _config(game / "dgVoodoo.conf")
    _require(overlay.is_file(), "--overlay não existe ou não é arquivo")
    _pe_x86(overlay, "overlay DLL")
    _require(captions.is_file(), "--captions não existe ou não é arquivo")
    _captions(captions)
    captions_sha = sha256(captions)
    _require(captions_sha == EXPECTED_CAPTIONS_SHA256,
             "Legendas diferentes do corpus V6 conferido; revisar mapeamento e atualizar o candidato explicitamente")
    return {
        "schema": 1,
        "candidate_only": True,
        "runtime_verified": False,
        "campaign_coverage_claimed": False,
        "read_only": True,
        "game_path": str(game.resolve()),
        "overlay_path": str(overlay.resolve()),
        "captions_path": str(captions.resolve()),
        "hashes": {"kain2.exe": exe_sha, "voices.dat": voices_sha,
                   "overlay": sha256(overlay), "captions": captions_sha},
        "caption_count": CAPTION_COUNT,
        "errors": [],
    }


def validate_output_path(output_path: Path, game: Path) -> Path:
    output = Path(output_path).resolve()
    _require(not output.exists(), "--output precisa apontar para arquivo novo; sobrescrita recusada")
    roots = [(ROOT / "validate").resolve(), (ROOT / "staging").resolve()]
    _require(any(output == root or root in output.parents for root in roots),
             "--output deve ficar dentro de validate/ ou staging/")
    game_resolved = Path(game).resolve()
    _require(output != game_resolved and game_resolved not in output.parents,
             "--output não pode ficar dentro da cópia indicada por --game")
    return output


def write_report(report: dict, output_path: Path, game: Path) -> None:
    output = validate_output_path(output_path, game)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path, help="cópia isolada dentro do repositório/staging")
    parser.add_argument("--overlay", required=True, type=Path, help="DLL overlay candidata PE x86")
    parser.add_argument("--captions", required=True, type=Path, help="JSON Unicode captions paginado")
    parser.add_argument("--output", required=True, type=Path, help="caminho novo para relatório JSON")
    args = parser.parse_args(argv)
    try:
        output = validate_output_path(args.output, args.game)
        inputs = (args.game, args.overlay, args.captions)
        _require(all(output != Path(item).resolve() for item in inputs),
                 "--output não pode coincidir com arquivo ou diretório de entrada")
        report = preflight(args.game, args.overlay, args.captions)
        write_report(report, output, args.game)
    except (PreflightError, OSError) as exc:
        print(json.dumps({"candidate_only": True, "runtime_verified": False, "errors": [str(exc)]}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
