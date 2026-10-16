"""Offline catalogue and pilot package builder. JSON on stdout; diagnostics on stderr."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave

from inspect_voices import EXE_SHA256, VOICES_SHA256, RATE, inspect

ROOT = Path(__file__).resolve().parent.parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def destination(game, output):
    output = output.resolve()
    if output.is_relative_to(game.resolve()) or output.exists():
        raise ValueError("Choose a new output directory outside the source installation")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(pcm)


def validate_voice_namespace(data):
    """Video dialogue IDs are local to a movie, not indices in voices.dat."""
    if data.get("resource_kind", "voices.dat") != "voices.dat":
        raise ValueError("FMV/resource plan cannot be used for voices.dat slots")
    for voice in data.get("voices", []):
        if "fmv" in voice:
            raise ValueError("FMV dialogue IDs cannot be used as voices.dat slot IDs")


def catalogue(game, output, workers):
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    pcm, rows = inspect(game)
    output = destination(game, output)
    with tempfile.TemporaryDirectory(prefix=".catalogue-", dir=output.parent) as temporary:
        root = Path(temporary)
        (root / "audio").mkdir()

        def extract(row):
            chunk = pcm[row["offset"]:row["offset"] + row["length"]]
            filename = f"audio/{row['id']:04d}.wav"
            write_wav(root / filename, chunk)
            return dict(row, source="voices.dat", source_pcm_sha256=digest(chunk),
                        original_audio=filename, speaker=None, text_en=None,
                        text_ptbr=None, approved_text=False, approved_audio=False)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            entries = list(pool.map(extract, rows))
        atomic_json(root / "catalogue.json", dict(schema=1, game="sr1-steam-classic-en",
                    exe_sha256=EXE_SHA256, voices_sha256=VOICES_SHA256,
                    profiles={}, voices=entries))
        root.rename(output)
    return dict(schema=1, catalogue=str(output / "catalogue.json"), entries=len(entries),
                duration_seconds=len(pcm) / (RATE * 2), workers=workers)


def _approval_rows(value, key, label):
    rows = value.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"{label}: {key} must be a list")
    indexed = {}
    for row in rows:
        ident = row.get("id") if isinstance(row, dict) else None
        if type(ident) is not int or ident < 0 or ident in indexed:
            raise ValueError(f"{label}: invalid or duplicate ID")
        indexed[ident] = row
    return indexed


def verify_approval_sources(plan_voices, audio_approval_path, text_approval_path):
    """Verify package plan entries against the user hash-bound audio/text ledgers."""
    if (audio_approval_path is None) != (text_approval_path is None):
        raise ValueError("both audio and text approval manifests are required together")
    if audio_approval_path is None:
        return None
    audio_path, text_path = Path(audio_approval_path).resolve(strict=True), Path(text_approval_path).resolve(strict=True)
    if not audio_path.is_relative_to(ROOT) or not text_path.is_relative_to(ROOT):
        raise ValueError("approval manifests must be inside the repository")
    audio_raw, text_raw = audio_path.read_bytes(), text_path.read_bytes()
    audio = json.loads(audio_raw.decode("utf-8-sig"))
    text = json.loads(text_raw.decode("utf-8-sig"))
    if audio.get("schema") != 1 or audio.get("artifact_type") != "user-voice-audio-approval-ledger":
        raise ValueError("audio approval ledger is invalid")
    if text.get("schema") != 1 or text.get("artifact_type") != "user-approved-ptbr-dialogue-texts":
        raise ValueError("text approval manifest is invalid")
    if text.get("source_audio_approval", {}).get("sha256") != digest(audio_raw):
        raise ValueError("text approval is not bound to this audio approval ledger")
    review_ref = text.get("source_review", {})
    review_path = (ROOT / review_ref.get("path", "")).resolve(strict=True)
    if not review_path.is_relative_to(ROOT) or digest(review_path.read_bytes()) != review_ref.get("sha256"):
        raise ValueError("text approval source review hash mismatch")
    review = read_json(review_path)
    gallery_ref = audio.get("source_manifest", {})
    gallery_path = (ROOT / gallery_ref.get("path", "")).resolve(strict=True)
    if not gallery_path.is_relative_to(ROOT) or digest(gallery_path.read_bytes()) != gallery_ref.get("sha256"):
        raise ValueError("audio approval source gallery hash mismatch")
    if (review.get("approval_ledger_sha256") != digest(audio_raw)
            or review.get("source_gallery_sha256") != gallery_ref.get("sha256")):
        raise ValueError("review manifest does not link the current audio approval and source gallery")
    text_rows = _approval_rows(text, "takes", "text approval")
    audio_rows = _approval_rows(audio, "takes", "audio approval")
    proposal_ref = text.get("source_text_proposal", {})
    proposal_path = (ROOT / proposal_ref.get("path", "")).resolve(strict=True)
    if not proposal_path.is_relative_to(ROOT) or digest(proposal_path.read_bytes()) != proposal_ref.get("sha256"):
        raise ValueError("text approval source proposal hash mismatch")
    proposal = read_json(proposal_path)
    if (proposal.get("artifact_type") != "ptbr-text-review-import-proposal"
            or proposal.get("proposal_only") is not True
            or proposal.get("proposed_text_approval_count") != len(text_rows)):
        raise ValueError("text approval is not linked to a complete review proposal")
    if (len(text_rows) != text.get("approved_count")
            or len(audio_rows) != audio.get("audio_approved_count")
            or set(text_rows) != set(audio_rows)):
        raise ValueError("audio/text approvals must cover the same IDs")

    per_voice = {}
    for voice in plan_voices:
        ident = voice["id"]
        audio_row, text_row = audio_rows.get(ident), text_rows.get(ident)
        if audio_row is None or text_row is None:
            raise ValueError(f"Voice {ident}: missing from approval manifests")
        text_sha = digest(voice["text_ptbr"].encode("utf-8"))
        expected = (voice.get("speaker"), voice.get("audio_sha256"), voice.get("text_sha256"),
                    voice.get("seed"), voice.get("reference_audio_sha256"),
                    voice.get("metadata_provenance_chain", []))
        approved_audio = (audio_row.get("speaker"), audio_row.get("audio_sha256"), audio_row.get("seed"),
                          audio_row.get("reference_audio_sha256"), audio_row.get("metadata_provenance_chain", []))
        approved_text = (text_row.get("speaker"), text_row.get("audio_sha256"), text_row.get("text_sha256"),
                         text_row.get("text_ptbr"), text_row.get("text_approved"))
        if audio_row.get("audio_approved") is not True or expected[:2] + expected[3:] != approved_audio:
            raise ValueError(f"Voice {ident}: audio hash, speaker, seed, reference, or provenance differs from approval")
        if (voice.get("approved_audio") is not True or voice.get("approved_text") is not True
                or approved_text != (voice.get("speaker"), voice.get("audio_sha256"), text_sha,
                                     voice.get("text_ptbr"), True)
                or voice.get("text_sha256") != text_sha):
            raise ValueError(f"Voice {ident}: text/audio approval or exact text hash differs")
        per_voice[ident] = {
            "id": ident, "speaker": voice["speaker"], "text_sha256": text_sha,
            "audio_sha256": voice["audio_sha256"], "seed": voice.get("seed"),
            "reference_audio_sha256": voice.get("reference_audio_sha256"),
            "provenance_status": text_row.get("provenance_status"),
        }
    return {"audio_approval_sha256": digest(audio_raw), "text_approval_sha256": digest(text_raw),
            "voices": per_voice}


def build_package(game, plan, output, review=False, audio_approval=None, text_approval=None):
    data = read_json(plan)
    if data.get("schema") != 1 or not isinstance(data.get("voices"), list):
        raise ValueError("Unsupported production plan schema")
    validate_voice_namespace(data)
    approval_context = verify_approval_sources(data["voices"], audio_approval, text_approval)
    original, rows = inspect(game)
    output = destination(game, output)
    seen = set()
    patches = []
    payloads = {}
    patched = bytearray(original)
    # Validate the entire package before creating its directory.
    for voice in data["voices"]:
        index = voice.get("id")
        if type(index) is not int or not 0 <= index < len(rows) or index in seen:
            raise ValueError("Invalid or duplicate voice id")
        seen.add(index)
        if voice.get("approved_text") is not True or (voice.get("approved_audio") is not True and not review):
            raise ValueError(f"Voice {index}: text and audio must be explicitly approved")
        if not voice.get("speaker") or not voice.get("text_ptbr", "").strip():
            raise ValueError(f"Voice {index}: missing speaker or translated text")
        audio_path = (plan.parent / voice["audio"]).resolve()
        audio_bytes = audio_path.read_bytes()
        if digest(audio_bytes) != voice.get("audio_sha256"):
            raise ValueError(f"Voice {index}: approved audio hash differs")
        with wave.open(str(audio_path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, RATE, "NONE"):
                raise ValueError(f"Voice {index}: expected PCM16 mono 22050 Hz WAV")
            count = audio.getnframes()
            replacement = audio.readframes(count)
            if len(replacement) != count * 2 or not replacement:
                raise ValueError(f"Voice {index}: truncated or empty WAV")
        leading = voice.get("lead_samples", 0)
        if type(leading) is not int or leading < 0:
            raise ValueError("lead_samples must be a nonnegative integer")
        row = rows[index]
        if len(replacement) + leading * 2 > row["length"]:
            raise ValueError(f"Voice {index}: audio exceeds slot; revise the take")
        samples = struct.unpack(f"<{count}h", replacement)
        peak = max(abs(s) for s in samples)
        if peak >= 32767 or peak < 4:
            raise ValueError(f"Voice {index}: clipping or effectively silent audio")
        payload = b"\0" * (leading * 2) + replacement
        payload += b"\0" * (row["length"] - len(payload))
        if payload == original[row["offset"]:row["offset"] + row["length"]]:
            raise ValueError(f"Voice {index}: payload is identical to the original; no replacement exists")
        name = f"voice-{index:04d}.pcm"
        payloads[name] = payload
        patches.append(dict(id=index, file=name, sha256=digest(payload), length=len(payload)))
        patched[row["offset"]:row["offset"] + row["length"]] = payload
    if not patches:
        raise ValueError("The package would contain no approved voices")
    manifest = dict(schema=1, id="sr1-ptbr-voice-candidate", name="Dublagem PT-BR — candidato parcial",
                    version="0.1.0", exe_sha256=EXE_SHA256, source_sha256=VOICES_SHA256,
                    result_sha256=digest(patched), patches=patches,
                    coverage=dict(replaced=len(patches), total=len(rows), complete=False),
                    runtime_verified=False)
    if approval_context:
        manifest["approval_sources"] = {
            "audio_ledger_sha256": approval_context["audio_approval_sha256"],
            "text_approval_sha256": approval_context["text_approval_sha256"],
        }
        manifest["voice_approvals"] = list(approval_context["voices"].values())
    if review:
        manifest.update(id="sr1-ptbr-review", name="Candidato PT-BR — escuta pendente")
    with tempfile.TemporaryDirectory(prefix=".package-", dir=output.parent) as temporary:
        root = Path(temporary)
        for filename, payload in payloads.items():
            (root / filename).write_bytes(payload)
        atomic_json(root / "manifest.json", manifest)
        if review:
            atomic_json(root / "review.json", dict(schema=1, human_listening_approved=False,
                        status="Experimental candidate for isolated playback review",
                        manifest_sha256=digest((root / "manifest.json").read_bytes()),
                        voices=data["voices"]))
        root.rename(output)
    return dict(schema=1, manifest=str(output / "manifest.json"), voices=len(patches),
                result_sha256=manifest["result_sha256"])


def _indexed_rows(value, key, label):
    rows = value.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"{label}: {key} must be a list")
    indexed = {}
    for row in rows:
        ident = row.get("id") if isinstance(row, dict) else None
        if type(ident) is not int or ident < 0 or ident in indexed:
            raise ValueError(f"{label}: invalid or duplicate ID")
        indexed[ident] = row
    return indexed


def build_coverage(selection_plan, selection_manifest, audio_approval, exact_review,
                   vocalizations, duplicate_matrix):
    """Cross current local selection and human evidence into a 479-slot matrix."""
    paths = {
        "selection_plan": Path(selection_plan).resolve(strict=True),
        "selection_manifest": Path(selection_manifest).resolve(strict=True),
        "audio_approval": Path(audio_approval).resolve(strict=True),
        "exact_take_review": Path(exact_review).resolve(strict=True),
        "vocalization_triage": Path(vocalizations).resolve(strict=True),
        "duplicate_evidence": Path(duplicate_matrix).resolve(strict=True),
    }
    raw = {name: path.read_bytes() for name, path in paths.items()}
    sources = {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(raw[name])}
               for name, path in paths.items()}
    plan = json.loads(raw["selection_plan"].decode("utf-8-sig"))
    manifest = json.loads(raw["selection_manifest"].decode("utf-8-sig"))
    approvals = json.loads(raw["audio_approval"].decode("utf-8-sig"))
    review = json.loads(raw["exact_take_review"].decode("utf-8-sig"))
    triage = json.loads(raw["vocalization_triage"].decode("utf-8-sig"))
    duplicate_source = json.loads(raw["duplicate_evidence"].decode("utf-8-sig"))

    if plan.get("schema") != 1 or manifest.get("schema") != 1:
        raise ValueError("Unsupported selection plan or package manifest schema")
    selection = _indexed_rows(plan, "voices", "selection plan")
    patches = _indexed_rows(manifest, "patches", "selection package")
    if set(selection) != set(patches) or len(selection) != 230:
        raise ValueError("V6 plan and package must match exactly 230 unique slots")
    for ident, voice in selection.items():
        if not voice.get("audio") or not voice.get("audio_sha256"):
            raise ValueError(f"Selection slot {ident}: missing take path or hash")

    if approvals.get("artifact_type") != "user-voice-audio-approval-ledger":
        raise ValueError("Audio approval ledger has an unexpected artifact type")
    ledger = _indexed_rows(approvals, "takes", "audio approval ledger")
    if len(ledger) != 223 or approvals.get("audio_approved_count") != 223:
        raise ValueError("Expected 223 user-approved takes in the audio ledger")
    for ident, row in ledger.items():
        if ident not in selection or row.get("audio_approved") is not True:
            raise ValueError(f"Audio approval for slot {ident} is not a valid V6 take approval")
        if row.get("audio_sha256") != selection[ident].get("audio_sha256"):
            raise ValueError(f"Audio approval hash differs from V6 take for slot {ident}")

    exact = {}
    for row in review.get("voices", []):
        if (isinstance(row, dict) and row.get("approved_audio") is True
                and row.get("human_listening_approved") is True):
            ident = row.get("id")
            if type(ident) is not int or ident in exact:
                raise ValueError("Exact take review contains an invalid or duplicate ID")
            exact[ident] = row
    if set(exact) != {116, 163, 173, 206, 225, 307}:
        raise ValueError("Exact take review must contain the six hash-approved takes")
    for ident, row in exact.items():
        if ident not in selection or row.get("audio_sha256") != selection[ident].get("audio_sha256"):
            raise ValueError(f"Exact take approval hash differs from V6 take for slot {ident}")
    approved_ids = set(ledger) | set(exact)
    if len(approved_ids) != 229 or set(ledger) & set(exact):
        raise ValueError("Expected 229 distinct approved takes (223 ledger + 6 exact hashes)")

    vocal_rows = _indexed_rows(triage, "entries", "vocalization triage")
    vocal_ids = {ident for ident, row in vocal_rows.items()
                 if row.get("classification") == "nonverbal_vocalization"}
    if len(vocal_ids) != 67 or len(vocal_rows) != 67:
        raise ValueError("Expected exactly 67 individually classified nonverbal slots")

    inventory_rows = _indexed_rows(duplicate_source, "entries", "duplicate evidence")
    if set(inventory_rows) != set(range(479)):
        raise ValueError("Duplicate evidence must contain the 479 contiguous voices.dat IDs")
    duplicate_pairs = set()
    for ident, row in inventory_rows.items():
        links = row.get("duplicate_of", [])
        if not isinstance(links, list):
            raise ValueError(f"Duplicate evidence for slot {ident} must be a list")
        for other in links:
            if type(other) is not int or other not in inventory_rows or other == ident:
                raise ValueError(f"Invalid duplicate link for slot {ident}")
            reverse = inventory_rows[other].get("duplicate_of", [])
            if ident not in reverse:
                raise ValueError(f"Duplicate link {ident}<->{other} is not symmetric")
            duplicate_pairs.add(tuple(sorted((ident, other))))
    duplicate_ids = {ident for pair in duplicate_pairs for ident in pair}
    if len(duplicate_pairs) != 17 or len(duplicate_ids) != 34:
        raise ValueError("Expected 17 duplicate pairs covering 34 distinct slots")

    selected_ids = set(selection)
    if selected_ids & vocal_ids or selected_ids & duplicate_ids or vocal_ids & duplicate_ids:
        raise ValueError("Selection, vocalization, and duplicate evidence overlap; resolve before classifying")

    counts = {
        "fala_com_take": len(selected_ids),
        "vocalizacao": len(vocal_ids),
        "duplicata": len(duplicate_ids),
        "desconhecido": 479 - len(selected_ids | vocal_ids | duplicate_ids),
    }
    rows = []
    for ident in range(479):
        if ident in selected_ids:
            category = "fala_com_take"
        elif ident in vocal_ids:
            category = "vocalizacao"
        elif ident in duplicate_ids:
            category = "duplicata"
        else:
            category = "desconhecido"
        voice = selection.get(ident)
        rows.append({
            "id": ident,
            "classificacao": category,
            "tem_take_na_selecao_v6": voice is not None,
            "take_aprovado_por_escuta": ident in approved_ids,
            "texto_aprovado_na_selecao": bool(voice and voice.get("approved_text") is True),
            "audio_sha256_selecao": voice.get("audio_sha256") if voice else None,
            "duplicata_de": sorted(inventory_rows[ident].get("duplicate_of", [])),
        })

    text_without_take = [row["id"] for row in rows
                         if row["texto_aprovado_na_selecao"] and not row["tem_take_na_selecao_v6"]]
    text_without_approved_audio = [row["id"] for row in rows
                                   if row["texto_aprovado_na_selecao"]
                                   and not row["take_aprovado_por_escuta"]]
    return {
        "schema": 1,
        "artifact_type": "sr1-ptbr-voices-dat-coverage-matrix",
        "slot_namespace": "voices.dat",
        "total_slots": 479,
        "runtime_verified": False,
        "summary": counts,
        "selection_v6_count": len(selected_ids),
        "audio_approved_count": len(approved_ids),
        "audio_approval_sources": {"ledger_223": len(ledger), "exact_hash_review_6": len(exact)},
        "text_approved_without_any_take": text_without_take,
        "text_approved_without_approved_audio": text_without_approved_audio,
        "future_synthesis_ids": text_without_take,
        "duplicate_pairs": [list(pair) for pair in sorted(duplicate_pairs)],
        "sources": sources,
        "entries": rows,
        "limitations": [
            "A presença de um take num slot físico não prova cobertura de diálogos ou eventos da campanha.",
            "O ID 182 tem take candidato na V6, mas não tem aprovação de áudio; não é contado como take aprovado.",
            "Os 67 registros de vocalização foram confirmados como não verbais; personagem e evento não foram individualizados.",
            "Duplicata identifica igualdade física de áudio registrada na evidência de origem, não equivalência de evento.",
            "Esta matriz não comprova disparo natural, sincronia, mixagem nem reprodução no jogo.",
        ],
    }


def render_coverage_markdown(matrix):
    summary = matrix["summary"]
    lines = [
        "# Matriz de cobertura — 479 slots de `voices.dat`", "",
        "| Classificação | Slots |", "|---|---:|",
    ]
    for category in ("fala_com_take", "vocalizacao", "duplicata", "desconhecido"):
        lines.append(f"| `{category}` | {summary[category]} |")
    lines.extend([
        "", f"Takes com aprovação de áudio: **{matrix['audio_approved_count']}** "
        f"({matrix['audio_approval_sources']['ledger_223']} do ledger + "
        f"{matrix['audio_approval_sources']['exact_hash_review_6']} por hash).",
        "", "`fala_com_take` inclui presença de take selecionado, não significa que todos os takes estejam aprovados.",
        "", "| ID | Classificação | Take V6 | Áudio aprovado | Texto aprovado | Par duplicado |",
        "|---:|---|:---:|:---:|:---:|---:|",
    ])
    for row in matrix["entries"]:
        pair = ", ".join(map(str, row["duplicata_de"])) or "—"
        lines.append(
            f"| {row['id']} | `{row['classificacao']}` | "
            f"{'sim' if row['tem_take_na_selecao_v6'] else '—'} | "
            f"{'sim' if row['take_aprovado_por_escuta'] else 'não' if row['tem_take_na_selecao_v6'] else '—'} | "
            f"{'sim' if row['texto_aprovado_na_selecao'] else '—'} | {pair} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_text_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_coverage_artifacts(matrix, output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "cobertura-479.json", matrix)
    write_text_atomic(output_dir / "cobertura-479.md", render_coverage_markdown(matrix))
    summary = matrix["summary"]
    sources = "\n".join(
        f"- `{item['path']}` — SHA-256 `{item['sha256']}`"
        for item in matrix["sources"].values()
    )
    report = [
        "# Relatório de cobertura da dublagem — 479 slots", "",
        "## Resultado", "",
        "| Classe mutuamente exclusiva | Slots |",
        "|---|---:|",
        f"| Fala com take na seleção V6 | {summary['fala_com_take']} |",
        f"| Vocalização não verbal confirmada | {summary['vocalizacao']} |",
        f"| Slots em pares duplicados | {summary['duplicata']} |",
        f"| Desconhecidos após os cruzamentos | {summary['desconhecido']} |",
        "| **Total** | **479** |", "",
        "A soma fecha exatamente em 479. A categoria `fala_com_take` representa take "
        "presente na seleção/pacote V6; não equivale a aprovação de áudio.", "",
        "## Aprovação e síntese futura", "",
        "Há 229 takes com aprovação de áudio rastreável: 223 no ledger de aprovação e 6 "
        "aprovados por hash em `content/dialogue-review.json` (IDs 116, 163, 173, 206, 225 e 307). "
        "A seleção e o manifesto do pacote V6 contêm 230 takes.", "",
        "O ID 182 é a única fala com texto aprovado na seleção V6 sem aprovação de áudio. "
        "Ele **tem take candidato** na seleção, portanto não entra na lista de slots sem take "
        "nem exige nova síntese com base apenas nesta matriz. A aprovação/escuta desse take "
        "continua pendente.", "",
        "**Lista de texto aprovado sem qualquer take: vazia.** Não há IDs para síntese futura "
        "com base na ausência de take. Se a escuta do ID 182 rejeitar o candidato existente, "
        "uma nova síntese poderá ser considerada depois; nenhum áudio foi gerado nesta tarefa.", "",
        "## Interpretação e limites", "",
        "Esta é cobertura de slots físicos de `voices.dat`, não cobertura de diálogos da campanha. "
        "O denominador de falas/eventos naturais da campanha não está estabelecido; portanto "
        "230/479 não representa percentual de diálogos dublados e não comprova 100% de dublagem.", "",
        "Os 67 slots de vocalização foram classificados pelo usuário como gemidos, gritos ou risadas; "
        "o subtipo, personagem e evento de cada slot não foram individualizados. Os 34 slots "
        "duplicados formam 17 pares por hash físico, o que não prova equivalência de uso em cena.", "",
        "A matriz é evidência estática. Não comprova disparo natural no jogo, sincronismo, mixagem "
        "ou reprodução em runtime; runtime não foi executado.", "",
        "## Fontes (SHA-256)", "", sources, "",
        "A matriz completa em JSON e a tabela de 479 linhas estão em `cobertura-479.json` "
        "e `cobertura-479.md`.", "",
    ]
    write_text_atomic(output_dir / "RELATORIO.md", "\n".join(report))
    return {"json": str(output_dir / "cobertura-479.json"),
            "markdown": str(output_dir / "cobertura-479.md"),
            "report": str(output_dir / "RELATORIO.md"), "summary": matrix["summary"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cat = commands.add_parser("catalogue", help="Extract exact slots and create a review catalogue")
    cat.add_argument("--workers", type=int, default=4)
    package = commands.add_parser("package", help="Package only approved, hash-pinned PCM voices")
    package.add_argument("--plan", type=Path, required=True)
    package.add_argument("--review-candidate", action="store_true",
                         help="Create an explicitly unapproved candidate for isolated listening/playback review")
    package.add_argument("--audio-approval", type=Path, help="hash-bound user audio approval ledger")
    package.add_argument("--text-approval", type=Path, help="hash-bound user PT-BR text approval manifest")
    coverage = commands.add_parser("coverage", help="Generate a reproducible 479-slot coverage matrix")
    coverage.add_argument("--selection-plan", type=Path,
                          default=ROOT / "staging/campaign-assembly/selection-v6/plan.json")
    coverage.add_argument("--selection-manifest", type=Path,
                          default=ROOT / "staging/campaign-assembly/selection-v6/package/manifest.json")
    coverage.add_argument("--audio-approval", type=Path,
                          default=ROOT / "validate/85-approval-voices/voice-approval.json")
    coverage.add_argument("--exact-review", type=Path, default=ROOT / "content/dialogue-review.json")
    coverage.add_argument("--vocalizations", type=Path,
                          default=ROOT / "validate/69-vocalization-triage/user-classification.json")
    coverage.add_argument("--duplicate-matrix", type=Path,
                          default=ROOT / "validate/18-cobertura-falas/matriz.json")
    coverage.add_argument("--output-dir", type=Path,
                          default=ROOT / "validate/97-dublagem-cobertura")
    for command in (cat, package):
        command.add_argument("--game", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "coverage":
            matrix = build_coverage(args.selection_plan, args.selection_manifest, args.audio_approval,
                                    args.exact_review, args.vocalizations, args.duplicate_matrix)
            result = write_coverage_artifacts(matrix, args.output_dir)
        elif args.command == "catalogue":
            result = catalogue(args.game, args.output, args.workers)
        else:
            result = build_package(args.game, args.plan, args.output, args.review_candidate,
                                   args.audio_approval, args.text_approval)
        print(json.dumps(result, ensure_ascii=False))
    except KeyboardInterrupt:
        parser.exit(130, "Interrupted; no package/catalogue was promoted.\n")
    except BrokenPipeError:
        pass
    except (OSError, ValueError, KeyError, TypeError, wave.Error) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
