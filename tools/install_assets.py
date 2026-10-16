"""Install/restore local UI and Bink candidates with hash checks and external backups.

Manifest: {schema: 1, assets: [{file, source_sha256, result_sha256, payload}]}.
Payload paths are relative to the manifest. Existing third-party DLLs are refused.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from audio_pipeline import atomic_json
from inspect_voices import EXE_SHA256

ALLOWED = {"locals.pc", "intro.bik", "verse.bik", "chrono3.bik", "chrono5.bik",
           "chrono7.bik", "chrono9.bik", "chrono11.bik", "chrono13.bik"}
CREATED_ONLY = {"DINPUT.dll", ".soul-reaver-ptbr/subtitles.tsv"}
ALLOWED |= CREATED_ONLY


def sha(data):
    return hashlib.sha256(data).hexdigest()


def current_bytes(path):
    path = regular(path)
    return path.read_bytes() if path.exists() else None


def current_sha(path):
    data = current_bytes(path)
    return sha(data) if data is not None else None


def regular(path):
    path = Path(path)
    # Check the complete path to avoid writes through a link/junction parent.
    for part in (path, *path.parents):
        if part.exists():
            info = part.lstat()
            if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Link/junction refused: {part}")
    return path


def load(path):
    return json.loads(regular(path).read_text(encoding="utf-8-sig"))


def atomic_bytes(path, data):
    regular(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def closed():
    if os.name == "nt":
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "if (Get-Process kain2 -ErrorAction SilentlyContinue) { exit 1 }"],
                                capture_output=True)
        if result.returncode:
            raise ValueError("Feche o jogo antes de instalar/restaurar arquivos.")


@contextlib.contextmanager
def locked(game):
    root = regular(game / ".soul-reaver-ptbr")
    root.mkdir(exist_ok=True)
    with regular(root / "operation.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield root / "assets-state.json"
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def validate_state(state, game):
    if state.get("schema") != 1 or state.get("game") != str(game):
        raise ValueError("Registro de arquivos incompatível")
    seen = set()
    for entry in state["assets"]:
        name = entry["file"]
        if name not in ALLOWED or name in seen:
            raise ValueError("Arquivo gerenciado inválido/duplicado")
        seen.add(name)
        if name in CREATED_ONLY:
            if entry["source_sha256"] is not None or entry["backup"] is not None:
                raise ValueError("Arquivo novo não pode substituir um arquivo preexistente")
        else:
            backup = regular(Path(entry["backup"]))
            if backup.resolve().is_relative_to(game):
                raise ValueError("Backup deve ficar fora da instalação")
            if sha(backup.read_bytes()) != entry["source_sha256"]:
                raise ValueError(f"Backup alterado: {name}")
        expected = {entry["source_sha256"], entry["result_sha256"]}
        if "previous_sha256" in entry:
            expected.add(entry["previous_sha256"])
        if current_sha(game / name) not in expected:
            raise ValueError(f"Conflito: {name} mudou após a instalação; preservado")


def install(game, manifest, backup_dir):
    game = regular(game).resolve()
    manifest = regular(manifest).resolve()
    backup_dir = regular(backup_dir).resolve()
    if backup_dir.is_relative_to(game):
        raise ValueError("Backup deve ficar fora da instalação")
    if sha(regular(game / "kain2.exe").read_bytes()) != EXE_SHA256:
        raise ValueError("Executável incompatível")
    plan = load(manifest)
    if plan.get("schema") != 1 or not plan.get("assets"):
        raise ValueError("Manifesto inválido")
    with locked(game) as journal:
        closed()
        state = load(journal) if journal.exists() else dict(schema=1, game=str(game), assets=[])
        validate_state(state, game)
        by_name = {entry["file"]: entry for entry in state["assets"]}
        seen, changes = set(), []
        # Validate the entire operation before writing a backup or game asset.
        for item in plan["assets"]:
            name = item["file"]
            if name not in ALLOWED or name in seen:
                raise ValueError("Nome de arquivo inválido/duplicado")
            seen.add(name)
            if (name in CREATED_ONLY) != (item["source_sha256"] is None):
                raise ValueError("DLL/legendas exigem origem ausente e propriedade registrada")
            data = regular(manifest.parent / item["payload"]).read_bytes()
            if sha(data) != item["result_sha256"] or item["result_sha256"] == item["source_sha256"]:
                raise ValueError(f"Candidato inválido: {name}")
            current = current_bytes(game / name)
            current_hash = sha(current) if current is not None else None
            previous = by_name.get(name)
            if previous and previous["source_sha256"] != item["source_sha256"]:
                raise ValueError(f"Base original diferente: {name}")
            if current_hash not in {item["source_sha256"], previous["result_sha256"] if previous else item["source_sha256"]}:
                raise ValueError(f"Arquivo original desconhecido: {name}")
            backup = None if name in CREATED_ONLY else Path(previous["backup"]) if previous else backup_dir / (name + ".original")
            if backup is not None:
                regular(backup)
            if backup is not None and backup.exists() and sha(backup.read_bytes()) != item["source_sha256"]:
                raise ValueError(f"Backup existente diferente: {name}")
            entry = dict(file=name, source_sha256=item["source_sha256"],
                         result_sha256=item["result_sha256"], previous_sha256=current_hash,
                         backup=str(backup) if backup is not None else None)
            changes.append((entry, data, current))
        backup_dir.mkdir(parents=True, exist_ok=True)
        for entry, _, current in changes:
            if entry["backup"] is None:
                continue
            backup = Path(entry["backup"])
            if not backup.exists():
                with backup.open("xb") as output:
                    output.write(current)
                    output.flush()
                    os.fsync(output.fileno())
            if sha(backup.read_bytes()) != entry["source_sha256"]:
                raise ValueError("Falha ao conferir backup")
        # Record all owners before mutation; interrupted operations are restorable.
        for entry, _, _ in changes:
            by_name[entry["file"]] = entry
        state.update(phase="preparing", assets=list(by_name.values()))
        atomic_json(journal, state)
        for entry, data, current in changes:
            closed()
            target = game / entry["file"]
            if current_bytes(target) != current:
                raise ValueError("Arquivo mudou durante a instalação")
            atomic_bytes(target, data)
            if sha(target.read_bytes()) != entry["result_sha256"]:
                raise ValueError("Falha ao conferir arquivo instalado")
        state["phase"] = "installed"
        atomic_json(journal, state)
        return state


def restore(game):
    game = regular(game).resolve()
    with locked(game) as journal:
        closed()
        state = load(journal)
        validate_state(state, game)
        state["phase"] = "restoring"
        atomic_json(journal, state)
        for entry in state["assets"]:
            closed()
            validate_state(state, game)
            target = game / entry["file"]
            if entry["backup"] is None:
                # Only files created by this journal, still matching its hash, reach here.
                if current_bytes(target) is not None:
                    regular(target).unlink()
            else:
                atomic_bytes(target, Path(entry["backup"]).read_bytes())
        state["phase"] = "restored"
        atomic_json(journal, state)
        validate_state(state, game)
        return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "restore"))
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "install":
            if not args.manifest or not args.backup_dir:
                parser.error("install requires --manifest and --backup-dir")
            result = install(args.game, args.manifest, args.backup_dir)
        else:
            result = restore(args.game)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Erro: {error}\n")
