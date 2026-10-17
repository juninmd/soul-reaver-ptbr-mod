#!/usr/bin/env python3
"""11ª identidade: vampiro genérico, para as provocações curtas de inimigos.

Referência: áudio original de uma provocação de vampiro do próprio jogo
(ID 152, "Damned one."), a mais longa do grupo, para dar identidade ao clone.
Autorizado pelo usuário em 16/10/2026.

Só entram as provocações com intenção clara. As transcrições de ASR que são
ruído (ex.: 108 "Tractor!", 127 "Brazil.", 47 "Played out 63.") ficam de fora.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES_FROM = ROOT / "staging/campaign-dub-v10/plan.json"
DURATIONS_FROM = ROOT / "validate/104-revisao-desconhecidos/revisao-148.json"
OUT_DIR = ROOT / "staging/campaign-dub-v18-vampiro"
REFERENCE = ROOT / "staging/catalogue-v1/audio/0152.wav"
REFERENCE_TEXT = "Damned one."

LOTE = {
    97: "Caído!",
    105: "Maldito!",
    106: "Infiel!",
    109: "Caído!",
    113: "Infiel!",
    125: "Caído!",
    130: "Maldito!",
    132: "Infiel!",
    136: "Herege!",
    44: "Maldito.",
    48: "Maldito!",
    152: "Maldito.",
    170: "Intruso!",
}

ASR = {
    97: "Fallen!", 105: "Damned one!", 106: "Infidel!", 109: "Fallen!",
    113: "Infidel", 125: "Fallen!", 130: "Damm'd one!", 132: "IN FATAL!",
    136: "Heretic", 44: "Damned one.", 48: "Damn one!", 152: "Damned one.",
    170: "I'm Intruder!",
}


def main() -> int:
    profiles = json.loads(PROFILES_FROM.read_text(encoding="utf-8"))["profiles"]
    durations = {int(r["id"]): r["duracao_s"] for r in json.loads(DURATIONS_FROM.read_text(encoding="utf-8"))["itens"]}

    profiles["vampiro"] = {
        "reference": str(REFERENCE),
        "reference_sha256": hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
        "reference_text": REFERENCE_TEXT,
    }

    voices = []
    for i, text in sorted(LOTE.items()):
        voices.append({
            "id": i, "speaker": "vampiro", "text_ptbr": text,
            "duration_seconds": durations[i],
            "approved_text": True, "approved_audio": False,
            "original_audio": str(ROOT / f"staging/catalogue-v1/audio/{i:04d}.wav"),
            "source_asr_en": ASR[i],
            "provenance": "identidade 'vampiro' autorizada pelo usuario em 16/10/2026; texto pt-BR assistido",
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": 1, "language": "pt-BR",
        "scope": "11a identidade (vampiro generico) para provocacoes curtas de inimigos.",
        "profiles": profiles, "voices": voices,
        "source_translation": "ASR EN (validate/33-43-48) + traducao pt-BR assistida",
        "human_listening_approved": False,
    }
    (OUT_DIR / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ids": [v["id"] for v in voices], "total": len(voices), "profile": "vampiro"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
