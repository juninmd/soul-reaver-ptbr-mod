#!/usr/bin/env python3
"""Plano de síntese para as linhas `desconhecido` de locutor resolvido.

Atribuição defensável pelo conteúdo (narração/tutorial do Ancião; falas de Raziel
dirigidas a irmãos). As provocações curtas de inimigos ("Fallen!", "Infidel!",
"Heretic", "Damned one") ficam de fora: exigem uma voz genérica de vampiro, que
não está no elenco aprovado de 10 personagens.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES_FROM = ROOT / "staging/campaign-dub-v10/plan.json"
DURATIONS_FROM = ROOT / "validate/104-revisao-desconhecidos/revisao-148.json"
OUT_DIR = ROOT / "staging/campaign-dub-v17-ambiguos"

LOTE = {
    415: ("raziel", "Gratidão a quem o faria rastejar ao portão como um cão. Você já teve aspirações nobres, Turel. Agora, quão humildes são seus objetivos. Você prospera com as migalhas que ele lhe atira?", "Gratitude toward one who would have you grovel at his gate like a dog..."),
    382: ("raziel", "As coisas não mudaram tanto quanto você crê. Você sempre foi fraco, Zephon. E, mais uma vez, se curvará à minha vontade.", "Perhaps things have not changed as much as you'd like to believe..."),
    389: ("raziel", "Que lealdade. A quem o mantém guardando este posto como um cão acorrentado, você prospera com as migalhas que ele lhe atira?", "Such loyalty. To one who has you guarding this outpost like a chain dog..."),
    309: ("raziel", "Deixe-me passar, Turel. Já tenho sangue nas mãos. Minha rixa é com Kain.", "Let me pass, Turel. I have enough blood on my hands today..."),
    331: ("raziel", "Sua fé o abandonou. Onde estão seus preciosos vampiros agora? Onde está seu rei sagrado?", "Your faith has failed you. Where are your precious vampires now? Where is your holy king?"),
    347: ("elder", "As montanhas além dos pilares revelam um crime antigo. Use a Soul Reaver para abrir caminho e siga para o oeste.", "The mountains beyond the pillars expose an ancient crime..."),
}


def main() -> int:
    profiles = json.loads(PROFILES_FROM.read_text(encoding="utf-8"))["profiles"]
    durations = {int(r["id"]): r["duracao_s"] for r in json.loads(DURATIONS_FROM.read_text(encoding="utf-8"))["itens"]}
    voices = []
    for i, (speaker, text, asr) in sorted(LOTE.items()):
        voices.append({
            "id": i, "speaker": speaker, "text_ptbr": text,
            "duration_seconds": durations[i],
            "approved_text": True, "approved_audio": False,
            "original_audio": str(ROOT / f"staging/catalogue-v1/audio/{i:04d}.wav"),
            "source_asr_en": asr,
            "provenance": "locutor resolvido por conteudo; texto pt-BR por IA com aprovacao delegada em 16/10/2026",
        })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": 1, "language": "pt-BR",
        "scope": "Linhas antes desconhecidas com locutor resolvido (Anciao e Raziel).",
        "profiles": profiles, "voices": voices,
        "source_translation": "ASR EN (validate/33-43-48) + traducao pt-BR assistida",
        "human_listening_approved": False,
    }
    (OUT_DIR / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ids": [v["id"] for v in voices], "total": len(voices)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
