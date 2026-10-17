# Engenharia reversa: 4K, fundos de menu, 60 FPS e DualSense

Análise estática de `kain2.exe` (imagem base 0x400000, x86). Tudo aqui é **observado por disassembly**; nenhum item foi validado em runtime.

## Texturas 4K / HD
- `0x472BC0` e `0x472CD0` criam superfícies DirectDraw fixas 256×256 (sistema e vídeo).
- `0x4732A0` lê 0x20000 bytes de `textures.big` em `0x1000 + índice*0x20000` e chama `0x472E70`, que copia/converte ARGB1555 para a superfície.
- `0x468EC0` envia os polígonos ao D3D via `DrawPrimitive` (vtable +0xA0/+0x70); os UVs usam escala flutuante em `0x4EC378`.
- Os `hd-textures/page-*.raw` instalados não são lidos por nenhum código do jogo. O protótipo `hd_texture_cache.cpp` só funciona via Frida e aceita no máximo 32 páginas.
- Próximo passo: hook D3D11 no `DINPUT.dll` (que o jogo sempre carrega) ou patch em `0x472BC0`/`0x472E70`.

## Fundos de menu
- `title1.pti` (idx 92): `0x439595`, `0x439E6A`. `bkgdmenu.pti` (idx 90): estado 6, `0x47F0BD` e similares. `bigback.pti` (idx 91): estado 5, `0x47EE2E`.
- Desenho: `0x47AA80` -> `0x472420` (blit 512×480 para superfície de 0x200×0x1E0, 32 ou 16 bpp).
- `menu_background_overlay.cpp` falha com `E_INVALIDARG` porque exige RTV `R8G8B8A8_UNORM`, e o dgVoodoo entrega outro formato (descritor observado com `format: 27`).

## 60 FPS
- `0x4AC3E0` integra o tempo: `incremento = (delta_ms << 12) / 33`, quantum `0x1000` (= 33 ms). Globais: `0xC66F60` (delta), `0xC66F80` (passo ocorreu), `0xC66E50` (contador), `0xC66F88` (modo 1/2, limites 0x21 e 0x32 ms).
- Limitador por espera ativa: `0x4390D0` (menu) e `0x439BD9` (33 ms = `0x21`).
- Desbloquear exige separar simulação (33 ms) de renderização/Present, ou dobrar a taxa de passo e escalar todos os consumidores de `0xC66F60` (150 leituras).

## DualSense / controle
- O jogo lê o pad no formato PSX em `0xC61040` (status, tipo 0x41/0x73/0x53, botões active-low em +2, sticks em +6/+7), traduzido em `0x4AD440`; a tabela de máscaras está em `0x4F5620`/`0x4F5660`.
- Inicialização do buffer: `0x4AD2E0`. Um shim no `DINPUT.dll` pode preencher esse buffer antes de `0x4AD440`, sem emulação de teclado.
- Atual: `tools/controller/bridge.cpp` usa `winmm` + `SendInput`.

## Achado adicional: caminho DirectInput nativo para joystick
- `0x478170` consulta o dispositivo DirectInput em `0xC52FB0` (Poll +0x1C, GetDeviceState +0x24, 0x50 bytes) e chama `0x478720(pad, DIJOYSTATE*)`, que preenche o buffer PSX (`0xC61040`, ponteiro em `0xC651C8` definido por `0x429A20`).
- Mapeamento: lX/lY (limiar zero, digital) para esquerda/direita/cima/baixo; botões 0-9 (`+0x30..+0x39`) para Quadrado, X, Círculo, Triângulo, L1, R1, L2, R2, Select, Start. Coincide com a ordem padrão DirectInput do DualSense.
- Lacunas: o D-pad do DualSense vem como POV hat (ignorado), L3/R3 e stick direito não são lidos, e o analógico é tratado como digital.
- Proposta (não implementada): o proxy `DINPUT.dll` envolve o `IDirectInputDevice::GetDeviceState` e traduz POV para lX/lY, sem emulação de teclado. Exige validação em runtime.
