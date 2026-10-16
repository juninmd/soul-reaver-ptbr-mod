"""Build an isolated, review-pending Unicode UI catalogue candidate."""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localize_ui

EXPECTED_SHA256 = localize_ui.SOURCE_SHA256
KEYS = (set(range(91, 95)) | set(range(107, 168))) - {108, 109, 159, 161, 162, 164}
SYMBOLS = {84, 168}

ADDITIONS = {
    30: "ok", 56: "gama", 83: "triângulo", 84: "x", 91: "i", 92: "j",
    93: "start", 94: "select", 107: "start", 108: "menu de glifos", 109: "zoom",
    110: "escape", 111: "backspace", 112: "tab", 113: "enter", 114: "l ctrl",
    115: "l shift", 116: "r shift", 117: "numpad *", 118: "l alt",
    120: "caps lock", 121: "f1", 122: "f2", 123: "f3", 124: "f4", 125: "f5",
    126: "f6", 127: "f7", 128: "f8", 129: "f9", 130: "f10", 131: "num lock",
    132: "scroll lock", 133: "numpad 7", 134: "numpad 8", 135: "numpad 9",
    136: "numpad -", 137: "numpad 4", 138: "numpad 5", 139: "numpad 6",
    140: "numpad +", 141: "numpad 1", 142: "numpad 2", 143: "numpad 3",
    144: "numpad 0", 145: "numpad .", 146: "f11", 147: "f12", 148: "f13",
    149: "f14", 150: "f15", 151: "numpad =", 152: "numpad enter", 153: "r ctrl",
    154: "numpad ,", 155: "numpad /", 156: "sysrq", 157: "r alt", 158: "home",
    160: "page up", 163: "end", 165: "page down", 166: "insert", 167: "delete",
    168: "~", 169: " ", 180: "a vida precisa estar cheia",
    181: "pressione o botão {0}", 214: "é preciso estar no plano material",
    215: "é preciso estar no plano espectral", 221: "carregando",
    222: "número de dica inválido", 223: "nenhum controle conectado à porta 1",
}

# Candidate wording, pending human review, for entries whose ASCII draft needs
# accents, clearer context, or a correction to the original first pass.
REVISIONS = {
    1: "formatar cartão de memória", 2: "lendo cartão no compartimento 1",
    5: "escolha um arquivo de Soul Reaver para carregar",
    6: "escolha um arquivo para salvar seu progresso",
    13: "não remova o cartão do compartimento 1", 16: "formatando cartão de memória",
    18: "insira um cartão no compartimento 1",
    19: "insira um cartão com pelo menos 3 blocos livres no compartimento 1",
    24: "música", 27: "nenhum cartão inserido", 28: "cartão cheio",
    29: "espaço insuficiente no cartão", 31: "opções",
    35: "deseja formatar o cartão?",
    36: "substituir os dados salvos no cartão do compartimento 1?",
    37: "deseja mesmo sair do jogo?", 47: "tente novamente ou insira outro cartão",
    48: "cartão não formatado", 52: "o jogo precisa de 3 blocos livres no cartão para salvar",
    53: "para salvar seu progresso, insira um cartão com 3 blocos livres no compartimento 1",
    55: "filtragem de texturas", 58: "usar este dispositivo", 59: "próximo dispositivo",
    60: "usar esta resolução", 61: "próxima resolução", 62: "dispositivo atual",
    63: "dispositivo sugerido", 64: "resolução atual", 65: "nova resolução",
    66: "largura", 67: "altura", 68: "profundidade de cor", 69: "escolher resolução",
    70: "escolher dispositivo", 71: "configuração de vídeo", 74: "controle",
    75: "teclado", 76: "comandos", 77: "configuração do controle",
    78: "configuração do teclado", 79: "cima", 80: "baixo", 81: "esquerda",
    82: "direita", 87: "superior frontal esquerdo", 88: "inferior frontal esquerdo",
    89: "superior frontal direito", 90: "inferior frontal direito", 95: "avançar",
    96: "recuar", 97: "esquerda", 98: "direita", 99: "pular/nadar",
    100: "devorar uma alma", 101: "mirar/agarrar", 102: "ação", 103: "agachar",
    104: "andar furtivo/encarar inimigo", 105: "mover a câmera para a esquerda",
    106: "mover a câmera para a direita", 119: "barra de espaço",
    159: "cima", 161: "esquerda", 162: "direita", 164: "baixo",
    170: "{0} para interagir", 171: "{0} + {1} para olhar", 172: "{0} para sair",
    173: "segure {0} para devorar", 174: "{0} para pular",
    175: "segure {0} + {1} para dar um salto alto", 176: "pule e segure {0} para planar",
    177: "segure {0} para encarar o inimigo", 178: "{0} para atacar",
    179: "encare o inimigo + {0} {1} {2} {3} e {4} para desviar",
    182: "{0} para mudar de plano", 184: "segure {0} para agarrar",
    185: "solte {0} para arremessar", 187: "segure {0} para agarrar",
    190: "{0} + {1} para soltar", 191: "segure {0} para mirar automaticamente",
    193: "segure {0} para empalar", 194: "segure {0} para andar furtivamente",
    195: "segure {0} para incendiar", 196: "{0} + {1} para dar uma cambalhota",
    199: "{0} + {1} {2} {3} {4} para rastejar",
    200: "{0}+{1} + {2} para mirar manualmente",
    201: "{0} para atravessar para o outro plano",
    206: "segure {0} + {1} para disparar em velocidade",
    207: "dê a volta no objeto para apertá-lo", 208: "{0}, {1} para escolher",
    209: "{0} para conjurar", 210: "segure {0} para descer devagar",
    212: "{0} ou {1} para girar a câmera", 213: "segure {0}+{1} para olhar ao redor",
    216: "{0} + {1} para planar", 217: "{0} para voltar",
    218: "{0} + {1} para dar um salto alto",
    219: "pressione {0} para atravessar para o outro plano",
    220: "{0}+{1} para olhar ao redor",
}

def decode_source(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Unknown source locals.pc SHA-256: {digest}")
    return localize_ui.decode(data)

def tokenize(raw, template):
    codes = [byte for byte in raw if byte >= 128]
    placeholders = [int(match) for match in re.findall(r"\{(\d+)\}", template)]
    if placeholders != list(range(len(codes))):
        raise ValueError(f"Icon placeholders do not match source bytes: {placeholders} vs {codes}")
    out = re.sub(r"\{(\d+)\}", lambda m: f"[icon:0x{codes[int(m.group(1))]:02X}]", template)
    rendered = [int(code, 16) for code in re.findall(r"\[icon:0x([0-9A-F]{2})\]", out)]
    if rendered != codes:
        raise ValueError(f"Rendered icons differ from source sequence: {rendered} vs {codes}")
    return out, codes

def build(source):
    raw_entries = decode_source(source)
    entries = []
    for i, raw in enumerate(raw_entries):
        source_display = "".join(f"[icon:0x{b:02X}]" if b >= 128 else chr(b) for b in raw).strip()
        source_text = raw.decode("latin1")
        if not raw or raw == b" ":
            text, status = "", "empty"
        elif i in KEYS:
            text, status = source_text.strip(), "key_label"
        elif i in SYMBOLS:
            text, status = source_text.strip(), "symbol"
        else:
            template = REVISIONS.get(i, ADDITIONS.get(i, localize_ui.TEXT.get(i, source_text)))
            text, _ = tokenize(raw, template)
            status = "translated"
        entries.append({
            "id": i,
            "sourcehex": raw.hex(),
            "source_display": source_display,
            "text_ptbr": text,
            "status": status,
            "preserveicons": [f"0x{b:02X}" for b in raw if b >= 128],
        })
    if len(entries) != 224 or {entry["id"] for entry in entries} != set(range(224)):
        raise ValueError("Catalogue must contain exactly one entry for each ID 0..223")
    for entry in entries:
        if unicodedata.normalize("NFC", entry["text_ptbr"]) != entry["text_ptbr"]:
            raise ValueError(f"Candidate text is not NFC at ID {entry['id']}")
    return {
        "schema": 1,
        "kind": "CANDIDATO",
        "source": "staging/backups/steam-classic-en/locals.pc.original",
        "source_sha256": EXPECTED_SHA256,
        "encoding": "UTF-8",
        "normalization": "NFC",
        "human_review": False,
        "integration": False,
        "entries": entries,
    }

def write_candidate(source, output):
    candidate = build(source.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(candidate, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return candidate

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = write_candidate(args.source, args.output)
    counts = {status: sum(e["status"] == status for e in candidate["entries"])
              for status in ("translated", "key_label", "symbol", "empty")}
    print(f"224 entries; " + ", ".join(f"{key}={value}" for key, value in counts.items()))

if __name__ == "__main__":
    main()
