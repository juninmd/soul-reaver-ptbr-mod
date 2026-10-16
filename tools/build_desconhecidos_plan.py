#!/usr/bin/env python3
"""Monta o plano de síntese do primeiro lote de slots `desconhecido` com fala real.

Curadoria manual: só entram linhas com diálogo legível (narração do Ancião e do
Raziel). Ficam de fora gritos e alucinações de ASR (ex.: IDs 341, 324, 313, 108,
104). Reaproveita os perfis de voz aprovados de `staging/campaign-dub-v10/plan.json`.

Saída: `staging/campaign-dub-v16-desconhecidos/plan.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES_FROM = ROOT / "staging/campaign-dub-v10/plan.json"
DURATIONS_FROM = ROOT / "validate/104-revisao-desconhecidos/revisao-148.json"
OUT_DIR = ROOT / "staging/campaign-dub-v16-desconhecidos"

# id: (speaker, text_ptbr, source_asr_en)
LOTE = {
    459: ("elder", "Está feito, Raziel. Seu destino se cumpriu. Embora tenha destruído todos que podiam chamá-lo de semelhante, o mundo nasce de novo. O ciclo de nascimento e morte, parado e estagnado por longos anos, volta a fluir. Você fez bem, meu servo.", "It is done, Raziel. Your destiny is fulfilled..."),
    451: ("elder", "Deste cume, o pináculo da Catedral Silenciada está ao seu alcance. Depressa, Raziel! Com a Soul Reaver assim reforçada, nenhum obstáculo deterá seu avanço, nenhum inimigo barrará seu caminho. Mas cuidado: os vampiros deste mundo sentem suas intenções e o perseguirão em fúria desesperada.", "From this summit, the pinnacle of the Silenced Cathedral is within your reach..."),
    438: ("elder", "Está feito. Seu destino se cumpriu. O ciclo de nascimento e morte, parado e estagnado por longos anos, volta a fluir. Você fez bem, meu servo.", "It is done. Your destiny is fulfilled..."),
    430: ("elder", "Até esta pequena medida da alma de Kain lhe concedeu um grande dom. Como seu mestre, agora pode passar ao plano material quando quiser. Ainda precisa restaurar toda a sua saúde, mas já não depende de um portal.", "Even this small measure of Kain's soul has conferred on you a great gift..."),
    425: ("elder", "Dumah e Turel, os irmãos que o lançaram no Abismo, recuaram com seus clãs para os ermos do norte de Nosgoth. O dom da alma de Rahab permite persegui-los, além de obstáculos antes intransponíveis.", "Dumah and Turel, your brothers who bore you into the Abyss..."),
    423: ("elder", "Além do turbilhão do Abismo, um túnel subterrâneo segue ao norte, até os territórios dos clãs de Dumah e Turel. Dotado da alma de Rahab, você pode nadar para entrar onde antes seu avanço era impedido.", "Beyond the maelstrom of the Abyss, a subterranean tunnel leads northward..."),
    397: ("elder", "Volte à cidadela humana, Raziel. O templo, apesar da fachada inofensiva, está podre até o âmago e, como um câncer, espalha sua corrupção pela cidade.", "Return to the human citadel, Raziel..."),
    395: ("elder", "Estas forjas são afinadas com a energia da Soul Reaver. Depois de batizar a espada nestas fontes elementais, a lâmina poderá ser imbuída desse elemento a qualquer momento.", "These forges are tuned to the Soul Reaver's energy..."),
    207: ("elder", "Que encontre paz aqui, Raziel.", "May you find peace here, Raziel."),
    208: ("elder", "Você testa minha paciência, Raziel.", "You try my patience, Raziel."),
    470: ("raziel", "Kain é deificado. Os clãs contam histórias sobre ele. Poucos sabem a verdade. Ele foi mortal um dia, como todos nós. Mas seu desprezo pela humanidade o levou a criar a mim e a meus irmãos. Eu sou Raziel, primogênito de seus tenentes. Servi a Kain por um milênio. Estive com ele e meus irmãos no alvorecer do Império. Juntos, forjamos as legiões que submeteram Nosgoth.", "Kain is deified. The clans tell tales of him..."),
    417: ("raziel", "Figuras misteriosas se moviam sob a cobertura da escuridão, seus mantos denunciando intenção de culto. Este templo parecia uma fonte de contágio. Eu encontraria um meio de infiltrar este covil de vampiros.", "Mysterious figures moved under cover of darkness..."),
    381: ("raziel", "Observei, invisível, enquanto vultos sombrios deslizavam pelos muros do templo. A cidade dormia, alheia ao perigo que rastejava logo ali fora.", "I watched unseen as shadowy figures slipped down the temple walls..."),
    377: ("raziel", "Que destino cruel. Suas almas se misturando, atadas para sempre. A recusa de Kain nos pilares as unira séculos antes.", "Such a dire fate. Their souls commingling, fettered eternally..."),
    371: ("raziel", "Que destino cruel, suas almas se misturando, atadas para sempre, tal como a recusa de Kain as unira séculos antes.", "Such a dire fate, their souls commingling, fettered eternally..."),
    293: ("raziel", "Embora a sala parecesse vazia, estes estandartes a identificavam claramente como a câmara de audiências de Turel.", "Though the room seemed vacant, these banners clearly identified it as Turel's audience chamber."),
}


def main() -> int:
    profiles = json.loads(PROFILES_FROM.read_text(encoding="utf-8"))["profiles"]
    durations = {int(r["id"]): r["duracao_s"] for r in json.loads(DURATIONS_FROM.read_text(encoding="utf-8"))["itens"]}

    voices = []
    for i, (speaker, text, asr) in sorted(LOTE.items()):
        if speaker not in profiles:
            raise SystemExit(f"perfil ausente: {speaker}")
        dur = durations.get(i)
        if not dur:
            raise SystemExit(f"duração ausente para {i}")
        voices.append({
            "id": i,
            "speaker": speaker,
            "text_ptbr": text,
            "duration_seconds": dur,
            "approved_text": True,
            "approved_audio": False,
            "original_audio": str(ROOT / f"staging/catalogue-v1/audio/{i:04d}.wav"),
            "source_asr_en": asr,
            "provenance": "lote desconhecido curado; texto pt-BR por IA com aprovacao delegada pelo usuario em 16/10/2026",
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": 1,
        "language": "pt-BR",
        "scope": "Primeiro lote de slots antes classificados como desconhecido; somente linhas com dialogo legivel.",
        "profiles": profiles,
        "voices": voices,
        "source_translation": "ASR em ingles (filas validate/33-43-48) + traducao pt-BR assistida",
        "human_listening_approved": False,
    }
    (OUT_DIR / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ids": [v["id"] for v in voices], "total": len(voices), "plan": str(OUT_DIR / "plan.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
