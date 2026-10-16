"""Exercise installer rejection and recovery cases on a fresh isolated copy.

The script only reads the Steam directory to obtain the known original
executable and voices backup. All CLI mutations happen below --work. It never
launches the game and refuses to overwrite an existing work directory.

Example:
  python tools/verify_installer_negatives.py --steam "D:\\SteamLibrary\\steamapps\\common\\Legacy of Kain Soul Reaver" \
      --bundle staging/packages/raziel-pilot-v1 --work validate/22-instalador-qa/negative-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXE_SHA256 = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a"
VOICES_SHA256 = "e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5"
REPO = Path(__file__).resolve().parents[1]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def find_original(name: str, expected: str, roots: list[Path]) -> Path:
    stem, _, suffix = name.rpartition(".")
    variants = [f"{name}.original", name]
    if stem:
        variants.append(f"{stem}.original.{suffix}")
    for root in roots:
        for variant in variants:
            candidate = root / variant
            if candidate.is_file() and sha256_file(candidate) == expected:
                return candidate
    raise FileNotFoundError(f"Original não encontrado para {name} ({expected[:12]}…)")


def cli_prefix(binary: Path | None) -> list[str]:
    if binary is not None:
        if not binary.is_file():
            raise FileNotFoundError(f"srmod não encontrado: {binary}")
        return [str(binary)]
    return ["cargo", "run", "--quiet", "-p", "soul-reaver-mod-core", "--bin", "srmod", "--"]


def run_cli(prefix: list[str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*prefix, *arguments], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False
    )


def assert_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{label} falhou ({result.returncode}):\n{result.stdout}\n{result.stderr}")


def evidence(case_dir: Path, name: str, result: subprocess.CompletedProcess[str]) -> dict:
    path = case_dir / f"{name}.txt"
    content = f"exit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    path.write_text(content, encoding="utf-8")
    return {"file": str(path), "sha256": sha256_file(path)}


def prepare_case(
    case_dir: Path, steam: Path, exe_source: Path, voices_source: Path,
    package_source: Path, manifest_name: str,
) -> tuple[Path, Path]:
    game = case_dir / "game"
    game.mkdir(parents=True)
    shutil.copyfile(exe_source, game / "kain2.exe")
    shutil.copyfile(voices_source, game / "voices.dat")
    if sha256_file(game / "kain2.exe") != EXE_SHA256:
        raise AssertionError("Executável reconstruído não corresponde à hash original")
    if sha256_file(game / "voices.dat") != VOICES_SHA256:
        raise AssertionError("Vozes reconstruídas não correspondem à hash original")

    package = case_dir / "package"
    package.mkdir()
    source_manifest = package_source / manifest_name
    manifest = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
    shutil.copyfile(source_manifest, package / manifest_name)
    for patch in manifest["patches"]:
        payload_name = patch["file"]
        source_payload = package_source / payload_name
        if not source_payload.is_file():
            raise FileNotFoundError(f"Payload ausente no bundle: {payload_name}")
        shutil.copyfile(source_payload, package / payload_name)
    return game, package / manifest_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steam", type=Path, required=True, help="Cópia original; somente leitura")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True, help="Diretório novo para as cópias isoladas")
    parser.add_argument("--srmod-bin", type=Path, default=None)
    args = parser.parse_args()

    steam = args.steam.resolve()
    bundle = args.bundle.resolve()
    work = args.work.resolve()
    if work.exists():
        raise FileExistsError(f"Recusando sobrescrever diretório existente: {work}")
    if inside(work, steam) or inside(steam, work):
        raise ValueError("--work não pode coincidir com nem ficar dentro/abranger a instalação Steam")
    if inside(work, bundle) or inside(bundle, work):
        raise ValueError("--work deve ser isolado do bundle de origem")

    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifesto ausente: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not manifest.get("patches"):
        raise ValueError("Manifesto sem patches")

    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    roots = [
        steam / ".soul-reaver-ptbr",
        local_app_data / "SoulReaverPTBR" / "backups" / "steam-classic-en",
        REPO / "staging/backups/steam-classic-en",
    ]
    exe_source = steam / "kain2.exe"
    if not exe_source.is_file() or sha256_file(exe_source) != EXE_SHA256:
        raise ValueError("kain2.exe da origem não é o original conhecido; cópia interrompida")
    voices_source = find_original("voices.dat", VOICES_SHA256, roots)

    work.mkdir(parents=True, exist_ok=False)
    prefix = cli_prefix(args.srmod_bin.resolve() if args.srmod_bin else None)
    cases: list[dict] = []

    # (a) A hand-edited managed file must prevent voice restore and stay intact.
    case_dir = work / "a-modified-restore"
    game, package = prepare_case(case_dir, steam, exe_source, voices_source, bundle, "manifest.json")
    applied = run_cli(prefix, "apply", str(game), str(package))
    assert_ok(applied, "Aplicação do caso de conflito")
    evidence_apply = evidence(case_dir, "apply", applied)
    voices = game / "voices.dat"
    modified = bytearray(voices.read_bytes())
    modified[0] ^= 0xFF
    voices.write_bytes(modified)
    restore = run_cli(prefix, "restore", str(game))
    evidence_restore = evidence(case_dir, "restore", restore)
    error = restore.stdout + restore.stderr
    if restore.returncode == 0 or "alterado após a instalação" not in error:
        raise AssertionError(f"Restore não foi bloqueado com erro claro: {error}")
    if voices.read_bytes() != modified:
        raise AssertionError("O restore alterou o arquivo manualmente modificado")
    cases.append({"case": "arquivo alterado bloqueia restore", "result": "PASS", "evidence": [evidence_apply, evidence_restore], "preservedSha256": sha256_file(voices)})

    # (b) A different manifest/package cannot replace an active installation.
    case_dir = work / "b-different-package"
    game, package = prepare_case(case_dir, steam, exe_source, voices_source, bundle, "manifest.json")
    first_apply = run_cli(prefix, "apply", str(game), str(package))
    assert_ok(first_apply, "Aplicação inicial do caso de pacote distinto")
    first_evidence = evidence(case_dir, "apply-first", first_apply)
    different = json.loads(package.read_text(encoding="utf-8-sig"))
    different["version"] = (str(different.get("version", "1")) + ".different")[:64]
    second_package = package.with_name("manifest-different.json")
    second_package.write_text(json.dumps(different, ensure_ascii=False, indent=2), encoding="utf-8")
    second_apply = run_cli(prefix, "apply", str(game), str(second_package))
    second_evidence = evidence(case_dir, "apply-different", second_apply)
    error = second_apply.stdout + second_apply.stderr
    if second_apply.returncode == 0 or "Restaure a instalação anterior" not in error:
        raise AssertionError(f"Pacote diferente não foi recusado claramente: {error}")
    cases.append({"case": "pacote diferente durante instalação ativa", "result": "PASS", "evidence": [first_evidence, second_evidence], "installedSha256": sha256_file(game / "voices.dat")})

    # (c) A journal left at preparing after an applied write remains restorable.
    case_dir = work / "c-preparing-restore"
    game, package = prepare_case(case_dir, steam, exe_source, voices_source, bundle, "manifest.json")
    applied = run_cli(prefix, "apply", str(game), str(package))
    assert_ok(applied, "Aplicação do caso de interrupção")
    evidence_apply = evidence(case_dir, "apply", applied)
    journal_path = game / ".soul-reaver-ptbr" / "state.json"
    state = json.loads(journal_path.read_text(encoding="utf-8"))
    state["phase"] = "preparing"
    journal_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    interrupted_hash = sha256_file(journal_path)
    restored = run_cli(prefix, "restore", str(game))
    evidence_restore = evidence(case_dir, "restore", restored)
    assert_ok(restored, "Restore após interrupção simulada")
    if sha256_file(game / "voices.dat") != VOICES_SHA256:
        raise AssertionError("Restore após interrupção não recuperou o original")
    cases.append({"case": "restore após journal preparing", "result": "PASS", "evidence": [evidence_apply, evidence_restore], "interruptedJournalSha256": interrupted_hash, "restoredVoicesSha256": sha256_file(game / "voices.dat")})

    report = {
        "schema": 1,
        "steamTouched": False,
        "gameLaunched": False,
        "sourceExecutableSha256": sha256_file(exe_source),
        "sourceVoicesSha256": sha256_file(voices_source),
        "cases": cases,
    }
    report_path = work / "negative-cases.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the small textual evidence, not executable/game or package payloads.
    for case_name in ("a-modified-restore", "b-different-package", "c-preparing-restore"):
        case_dir = work / case_name
        shutil.rmtree(case_dir / "game")
        shutil.rmtree(case_dir / "package")
    print(json.dumps({"passed": True, "cases": len(cases), "report": str(report_path), "reportSha256": sha256_file(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"FALHA: {error}", file=sys.stderr)
        sys.exit(1)
