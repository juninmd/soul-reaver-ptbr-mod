"""Build the verified classic PC localization table, outside the source game."""
import argparse
import hashlib
from pathlib import Path
import struct

SOURCE_SHA256 = "2244304cbf1d89f7aaee44c534cf185c0ffd037272deee909247727be1d54d84"

# The game's bitmap font uses high bytes for button icons. Text is deliberately
# ASCII Portuguese; UTF-8/Windows accents would overwrite those icons.
TEXT = {
    1: "formatar cartao de memoria", 2: "lendo cartao no compartimento 1",
    3: "voltar", 4: "cancelar", 5: "escolha um jogo de soul reaver para carregar",
    6: "escolha onde salvar seu progresso", 7: "confirmar", 8: "continuar",
    9: "controle", 10: "criar novo arquivo", 11: "criando arquivo salvo",
    12: "demonstracoes", 13: "nao remova o cartao do compartimento 1",
    14: "concluido", 15: "sair do jogo", 16: "formatando cartao de memoria",
    17: "voltar", 18: "insira um cartao no compartimento 1",
    19: "insira um cartao com 3 blocos livres no compartimento 1",
    20: "cartao invalido", 21: "falha ao carregar", 22: "carregar jogo",
    23: "carregando dados", 24: "musica", 25: "novo jogo", 26: "nao",
    27: "nenhum cartao presente", 28: "cartao cheio", 29: "blocos livres insuficientes",
    31: "opcoes", 32: "sobrescrever", 33: "pausado", 34: "pressione start",
    35: "deseja formatar?", 36: "sobrescrever os dados salvos no cartao do compartimento 1?",
    37: "sair do jogo?", 38: "sair do jogo", 39: "retomar", 40: "falha ao salvar",
    41: "salvar jogo", 42: "jogo salvo", 43: "salvando dados", 44: "som",
    45: "iniciar jogo", 46: "iniciar novo jogo", 47: "tente novamente ou insira outro cartao",
    48: "cartao nao formatado", 49: "vibracao desligada", 50: "vibracao ligada",
    51: "vozes", 52: "soul reaver precisa de 3 blocos livres para salvar",
    53: "para salvar seu progresso, insira um cartao com 3 blocos livres no compartimento 1",
    54: "sim", 55: "filtrar texturas", 57: "fixo", 58: "usar este dispositivo",
    59: "proximo dispositivo", 60: "usar esta resolucao", 61: "proxima resolucao",
    62: "dispositivo atual", 63: "novo dispositivo", 64: "resolucao atual",
    65: "nova resolucao", 66: "largura", 67: "altura", 68: "bits de cor",
    69: "escolher resolucao", 70: "escolher dispositivo", 71: "configuracao de video",
    72: "vazio", 73: "redefinir", 74: "controle", 75: "teclado", 76: "comandos",
    77: "configuracao do controle", 78: "configuracao do teclado", 79: "cima",
    80: "baixo", 81: "esquerda", 82: "direita", 83: "triangulo", 85: "quadrado",
    86: "circulo", 87: "superior esquerdo", 88: "inferior esquerdo",
    89: "superior direito", 90: "inferior direito", 95: "avancar", 96: "recuar",
    97: "esquerda", 98: "direita", 99: "pular/nadar", 100: "devorar alma",
    101: "mirar/agarrar", 102: "acao", 103: "agachar", 104: "furtivo/encarar",
    105: "camera esquerda", 106: "camera direita", 108: "menu de glifos",
    119: "espaco", 159: "cima", 161: "esquerda", 162: "direita", 164: "baixo",
    170: "{0} para interagir", 171: "{0} + {1} para ver", 172: "{0} para sair",
    173: "segure {0} para devorar", 174: "{0} para pular",
    175: "segure {0} + {1} para salto alto", 176: "pule e segure {0} para planar",
    177: "segure {0} para encarar", 178: "{0} para atacar",
    179: "encare + {0} {1} {2} {3} e {4} para esquivar", 180: "vida deve estar cheia",
    181: "pressione {0}", 182: "{0} para mudar de plano", 183: "{0} para abrir",
    184: "segure {0} para agarrar", 185: "solte {0} para arremessar",
    186: "{0} para empurrar", 187: "segure {0} para segurar",
    188: "{0} {1} {2} {3} para arrastar", 189: "{0} para pegar",
    190: "{0} + {1} para largar", 191: "segure {0} para mirar",
    192: "{0} para cancelar", 193: "segure {0} para empalar",
    194: "segure {0} para andar furtivo", 195: "segure {0} para incendiar",
    196: "{0} + {1} para virar", 197: "{0} para acionar",
    198: "segure {0} para acionar", 199: "{0} + {1} {2} {3} {4} para rastejar",
    200: "{0}+{1} + {2} para mirar", 201: "{0} para atravessar",
    202: "{0} para escalar", 203: "{0} para soltar", 204: "{0} para disparar",
    205: "{0} para nadar", 206: "segure {0} + {1} para acelerar",
    207: "circule o objeto para contrair", 208: "{0}, {1} para escolher",
    209: "{0} para conjurar", 210: "segure {0} para descer devagar",
    211: "{0} para agachar", 212: "{0} ou {1} para girar camera",
    213: "segure {0}+{1} para olhar", 214: "requer plano material",
    215: "requer plano espectral", 216: "{0} + {1} para planar", 217: "{0} para voltar",
    218: "{0} + {1} para salto alto", 219: "pressione {0} para atravessar",
    220: "{0}+{1} para olhar", 221: "carregando", 222: "numero de dica invalido",
    223: "nenhum controle na porta 1",
}


def decode(data):
    if len(data) < 16:
        raise ValueError("Truncated localization table")
    language, reserved, end, count = struct.unpack_from("<IIII", data)
    if count != 224 or end != len(data) or language != 0 or reserved != 0:
        raise ValueError("Unsupported localization table layout")
    offsets = struct.unpack_from(f"<{count}I", data, 16)
    if offsets[0] != 16 + count * 4 or list(offsets) != sorted(set(offsets)):
        raise ValueError("Invalid localization offsets")
    strings = []
    for i, offset in enumerate(offsets):
        limit = offsets[i + 1] if i + 1 < count else len(data)
        value = data[offset:limit]
        if not value.endswith(b"\0") or (i + 1 < count and b"\0" in value[:-1]):
            raise ValueError("Invalid localization string boundary")
        strings.append(value.rstrip(b"\0"))
    return strings


def build(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unknown locals.pc; original preserved")
    original = decode(data)
    translated = []
    for index, value in enumerate(original):
        if index in TEXT:
            icons = [chr(b) for b in value if b >= 128]
            value = TEXT[index].format(*icons).encode("latin1")
            if [b for b in value if b >= 128] != [b for b in original[index] if b >= 128]:
                raise ValueError(f"Button icons changed at {index}")
        translated.append(value)
    offset = 16 + 4 * len(translated)
    offsets, body = [], bytearray()
    for value in translated:
        offsets.append(offset + len(body))
        body.extend(value + b"\0")
    result = struct.pack("<IIII", 0, 0, offset + len(body), len(translated))
    result += struct.pack(f"<{len(offsets)}I", *offsets) + body
    assert decode(result) == translated
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = build(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(candidate)
    print(f"Built {len(candidate)} bytes; {len(TEXT)} translated entries; button icons preserved")
