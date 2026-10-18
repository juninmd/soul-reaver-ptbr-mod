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

## Intros e diálogo de setup (observado por disassembly; não validado em runtime)
- Tabela de intros em `0x4F44A8`, entradas de 0x38 bytes, word `+0x36` = próxima: `publogo.rpl(0) -> crylogo.rpl(1) -> legal.pti(5, "aperte enter") -> fim`. `intro.rpl` (2) só toca pelo atract mode (`0x43A031`). Patch: word em `0x4F44DE` de 1 para 5 (pula `crylogo`).
- O diálogo de resolução/som (recurso 0x71) é aberto sempre por `0x47AED0` (`DialogBoxParamA` em `0x47AF10`), chamado em `0x47A399` antes do loop principal (`0x439880`). Os valores vêm do registro (`HKLM\SOFTWARE\Crystal Dynamics\Legacy of Kain: Soul Reaver\1.00.000`: `RenderDeviceID`, `SoundDeviceID`, `ScreenWidth/Height/Depth`, `Windowed`...), carregados antes por `0x479CC0`; o OK do diálogo só regrava esses campos.
- Pular a chamada (`mov eax,1`) **derruba o jogo** (0xC0000005, ponteiro nulo): o `WM_INITDIALOG` monta tabelas usadas depois. Patch final: `call [DialogBoxParamA]` vira `call hook_setup_dialog`, que roda o diálogo original com alfa 0 e posta `IDOK` (id 1) quando o registro já tem a config. Shift no launch mantém o diálogo interativo.
- Menu de debug do engine tem flags "Skip First/All Puppet Shows" (`0xC66E64`/`0xC66DE4`, bit `0x800000`) e "Rendering Setup..." (`0x4F6ABC`); não é o menu do jogador.
- Lacuna: seleção de resolução/som no menu principal nativo exige UI própria; hoje o ajuste é pelo registro ou segurando Shift.

### Alt+Tab
DDRAW.dll+0x22A9E (dgVoodoo) faults with a null deref when handling WM_SIZE after the WM_DISPLAYCHANGE/style burst of an Alt+Tab. The game wndproc wrapper (window_trace.h) now catches the fault, logs 'Window message handler faulted; message dropped' and drops that message; 6 consecutive Alt+Tabs survived. Root cause inside dgVoodoo is not fixed.

### Estado real das texturas HD (runtime)
install_hd_textures_hook em runtime.cpp é um stub: nenhum hook é instalado e o log agora diz isso ('HD textures: not consumed by the game'). Antes registrava 'HD texture 1024x1024 hook active', o que era falso. Texturas 4K reais continuam pendentes do patch em 0x472BC0/0x472E70 ou de hook D3D.

### Perfil da pausa de ~5,6 s (medido)
Com .soul-reaver-ptbr/profile-load.flag o runtime amostra o EIP da thread do jogo durante pausas. A pausa de 5,6 s observada após o Enter é reprodução de vídeo Bink, não carga de fase: ~63% em ntdll (espera/sincronismo de quadro), ~18% em binkw32 e ~6% no driver de vídeo. Não há ponto quente de CPU a otimizar ali. Carga real de fase ainda não foi perfilada.

### Painel de configuração (F10)
F10 abre um painel (setas escolhem, Enter salva, Esc/F10 fecha) com a resolução interna. O valor vai para .soul-reaver-ptbr/settings.ini e o runtime troca o slot RegQueryValueExA do kain2.exe (IAT 0x4EC010) para servir ScreenWidth/ScreenHeight dessa configuração, sem gravar no HKLM (a sessão não é administradora). Vale a partir da próxima inicialização. Medido: com 1920x1080 salvo, o jogo leu os valores sobrescritos e 10 ocorrências extras do par 1920x1080 surgiram no heap do processo (ausentes sem o ini). Não há painel para o provedor de som: o ID salvo no registro é reutilizado.

### Teste de vibração
O flag .soul-reaver-ptbr/test-rumble.flag dispara um pulso de absorção de alma (L=0x60, R=0xD0, 400 ms). O log registra 'DualSense rumble write ... -> ok (bytes=48 err=0)' quando o relatório de saída USB 0x02 chega ao controle físico. Isso prova o caminho HID; não prova a sensação nem o gatilho em jogo.

### Teste da câmera e guarda externa do Alt+Tab
.soul-reaver-ptbr/test-camera.flag empurra o pitch em -100 e loga o tilt (base+0x864560+0xFE). Em jogo o valor muda na hora (39 -> -61), mas 600 ms depois o motor o reescreve (391/588), então um único empurrão não permanece: o efeito contínuo depende de o analógico aplicar o delta a cada quadro. Também: quando o dgVoodoo reassume o wndproc depois do nosso, uma guarda externa única é instalada por cima ('Outer window guard installed'); uma rodada de 48 trocas de foco com Enter terminou com o jogo vivo.

### Câmera: eixos corrigidos
No DirectInput do DualSense parado: lX=32511 lY=33028 lZ=32255 lRx=0 lRy=0 lRz=32511. O analógico direito é lZ (X) e lRz (Y); lRx/lRy são os gatilhos analógicos, com repouso em 0. O código antigo usava lRy/lRx como fallback do eixo vertical, então a câmera recebia empurrão máximo o tempo todo (tilt preso em 600). Agora só lZ/lRz contam, com zona morta normalizada, curva quadrática no pitch e rotação horizontal proporcional por modulação das teclas L2/R2 do motor. Medido: tilt parado = 0.

### Análise estática: pacote de terceiros e localização da área atual
Comparação byte a byte (offline, sem executar nada) do kain2.exe do repositório silentgameplays/Legacy-of-kain-series-Fix-Windows (GPL-3.0) com o original: mesmo tamanho (1080832) e só 5 regiões diferentes (237 bytes). Elas trocam o rótulo do menu de depuração 'FLY MODE' por 'VIEW VRAM' e substituem uma rotina de depuração por um visualizador de VRAM (512x240). Não há janela, FPS, mapa, câmera nem resolução nesse patch; o fmod.dll é um FMOD 5 comum. Nada disso é reaproveitado; serve só de confirmação de que o motor tem estruturas de depuração e que 'bigfile/texture-NNNNN.png' é uma convenção de extração de texturas, não um recurso do motor.

Nome da área atual: o buffer BSS em 0xC66D20 é a estrutura global do jogo (recebida como primeiro argumento por dezenas de funções; 0xC66D4C = +0x2C é o ponteiro do jogador usado pelo runtime). O texto 'Requesting level change for under1.' pertence a uma função de depuração em 0x4C6B20 que só liga o bit 0x200000 de 0xC66E64. O carregador de área monta '\kain2\area\%s\bin\%s.crm' em 0x4CF998 e 0x4D7008 (formato em 0x4FB4FC); o nome da área é o argumento %s desses dois pontos. Como o buffer está em BSS, o nome só se confirma em execução: fica para a rodada de validação, onde o runtime deve registrar o %s e o unit_id do jogador no log para trocar os unit_id supostos de g_sectors.

### Patch de áudio removido (hipótese para o problema de som)
Os dois push alterados (0x47DA4A: 0x1000→0x4000 e 0x47DA7D: 0x4000→0x10000) estão dentro de 0x47D920, o reprodutor de vídeo (FMV): o segundo é o tamanho passado a Player_InitSound do vídeo. Não eram streaming de salas, como o log dizia, e nunca houve medição de ganho. Um buffer de som de vídeo de 64 KB pode atrasar o áudio das cutscenes em relação à imagem (cerca de 0,7 s a 22 kHz estéreo 16 bits). O patch foi removido e os bytes originais ficam intactos. Isto é hipótese: não foi ouvido em jogo.

### Vídeos (FMV) e pular com Enter/Espaço/✕ (observado em runtime)
`intro.rpl` (a abertura, 211 s no pacote 2560x1440) toca dentro de uma única chamada a `Player_InitMovie` do `Winplay.dll` (0x47D992): o player do Steam roda o laço Bink inteiro (`BinkWait/DoFrame/NextFrame` + `PeekMessageA`) e só sai com `WM_KEYDOWN` Esc/Ctrl/Win, `WM_SYSKEYDOWN` ou `WM_QUIT`. Por isso Enter/Espaço nunca pulavam e o laço `FUN_00478c90` do exe nem chega a rodar. `fmv_trace.h` envolve 0x47D920 (loga início/fim com a duração), roda uma thread vigia (Enter, Espaço, ✕/○/Options do DualSense) e, ao soltar a tecla, posta um `WM_KEYDOWN VK_ESCAPE` na thread do jogo. Medido: Enter durante a abertura encerra em ~10 s e o jogo chega a `Area load: under` 0,7 s depois (antes: 211 s). Soltar a tecla antes de pular evita que o mesmo Enter confirme também a tela "aperte enter". Limite: o gamepad só é lido se o DirectInput do DualSense já estiver aberto.

### Texturas HD reais (1024x1024)
`hd_textures.h` aplica dois patches de 1 byte (0x472C23 e 0x472D33: `mov eax,0x100` -> `0x400`) para que as superfícies de textura (sistema e dispositivo) sejam 1024x1024, e envolve 0x472E70 (`void* page_upload(int page, const void* page256)`, cdecl): o original continua cuidando do bookkeeping dos slots; depois a superfície é travada de novo e reescrita com `hd-textures/page-NNNN.raw` (1024x1024 ARGB1555) convertendo para o formato da superfície com as mesmas tabelas de escala do motor (0xC400D8/E0/100, máscaras 0xC400C0..CC, bpp 0xC400BC). Sem o RAW da página, o 256x256 original é replicado 4x. Os UVs do motor são normalizados (escala 1/4096 em 0x4EC378), então nenhum outro código muda. Medido: log `HD textures: 1024x1024 pages active`, 21 uploads ao carregar `under`, sem exceção. Validado visualmente por captura interna (ver abaixo): cena de `under` em 3840x2160 sem corrupção nem sangramento visível nas bordas, mais nítida que as páginas nativas. Memória medida na área `under` (2 min parado, 3 amostras): HD ligado = 112 MB de working set, 93 MB privados, 379 MB de VRAM dedicada; `disable-hd-textures.flag` = 88 MB, 87 MB, 161 MB. Ou seja, +24 MB de RAM e ~+220 MB de VRAM por área, estáveis (sem crescimento em 2 min). A VRAM cresce com as páginas carregadas por área; o pior caso entre áreas e sessões longas atravessando várias salas ainda não foi medido. Desligar: criar `.soul-reaver-ptbr/disable-hd-textures.flag` ou apagar `hd-textures/`.

### Menu e overlay
- Painel F10 por DualSense: nas telas de menu, Create abre/fecha o painel (o mapa só vale no mundo); com o painel aberto, D-pad escolhe linha e opção, ✕ salva e ○ fecha, e a câmera/ações do pad ficam bloqueadas. Dica de menu: "F10 / Create · Resolução e som". Verificado só pelo caminho de código: `test-padnav.flag` reproduz Create, direita, ✕, ○ e o log mostra `Settings panel opened`, `Settings: saved resolution 1920x1080` e `Settings panel closed`. O controle físico não estava conectado, então os botões reais não foram testados.
- Menu nativo (varredura de strings do exe, só leitura): os únicos rótulos de som/vídeo no `.data` de `kain2.exe` são os do menu de debug (`SOUND DEBUG` 0x4F8480, `VOICE/SFX/MUSIC VOLUME` 0x4F84AC–0x4F84D0, `Resolution` 0x4F83B8). `ScreenWidth/Height/Depth`, `GammaLevel` e `SoundDeviceID` (0x4F5904–0x4F5938) são chaves de configuração do launcher, sem entrada de menu do jogador. O texto do menu do jogador vem do arquivo de textos localizado, não de strings do exe. Conclusão: não existe entrada nativa de resolução ou provedor de som para estender; criar uma exige código novo no menu do jogador (estados 5/6) e glifos de fonte, o que não foi feito. O painel F10/Create é o substituto.
- Dica "F10 · Resolução e som" aparece nas telas sem jogador na cena (aperte enter / menus); some ao entrar no jogo (log `Menu hint shown/hidden`). O menu de opções nativo continua não localizado; o painel F10 é o caminho de configuração.
- Legendas agora são desenhadas numa faixa de 25 % da altura (antes um bitmap 2560x1440 inteiro): 32–47 ms por troca de página contra 80–90 ms.
- Startup medido: o publogo começa ~1 s depois do DLL; não há atraso de inicialização relevante.

### Legendas dentro do quadro do jogo (frame_overlay.h)
A janela sobreposta das legendas dependia de ordem de janela (topmost), foco e composição do DWM, e na máquina do usuário só aparecia depois de um Alt+Tab. `frame_overlay.h` desenha o mesmo bitmap GDI+ (BGRA pré-multiplicado) direto no back buffer do jogo, no gancho de `IDXGISwapChain::Present` (o mesmo vtable de `frame_capture.h`, agora sempre instalado), com um shader de triângulo único e mistura pré-multiplicada, via contexto adiado e `ExecuteCommandList(..., TRUE)` para restaurar o estado do pipeline do jogo. A imagem fica dentro do quadro, então nenhuma ordem de janela ou DWM a esconde. A janela antiga continua como reserva automática: assume quando o jogo não apresenta pelo swap chain (carregamento, alguns vídeos; sem `Present` por 400 ms), ou quando a criação dos shaders/estados falha ou o desenho falha 3 vezes (log `In-frame overlay disabled…`). Desligar: criar `.soul-reaver-ptbr/disable-frame-overlay.flag`. Verificado por captura do próprio back buffer (3840x2160): o texto amarelo da legenda aparece na faixa inferior do quadro (~15 mil amostras na legenda ativa; a captura anterior nunca continha o overlay, que era outra janela). Não verificado: o aspecto na tela física do usuário além do relato "funcionou".

### Captura de quadro por dentro do processo (frame_capture.h)
As capturas de tela do Windows (BitBlt, PrintWindow, Desktop Duplication) nunca enxergaram a janela do jogo nesta máquina. `frame_capture.h` resolve lendo o back buffer onde o dgVoodoo2 apresenta: o vtable de `IDXGISwapChain` é compartilhado pela classe do DXGI, então uma swap chain descartável dá o slot de `Present` (índice 8) para o patch; com `.soul-reaver-ptbr/capture-enabled.flag` presente, criar `capture-frame.flag` grava `frame-NNN.bmp` (BGRA 32 bits, 3840x2160 na configuração atual) e loga `Frame capture saved`. O overlay de legendas/mapa é outra janela e não aparece nessa imagem. Só é instalado com a flag de habilitação; sem ela o jogo não é tocado.
