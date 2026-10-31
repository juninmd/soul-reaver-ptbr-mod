# DualSense no instalador

O painel **Controle DualSense** detecta DualSense e DualSense Edge expostos pelo
Windows, instala um acompanhante local e inicia o jogo com **Jogar com DualSense**.
Não exige DS4Windows, drivers virtuais ou conexão de rede durante o uso.

O acompanhante lê o controle pelo WinMM e envia os comandos do teclado padrão do
jogo somente quando a janela do processo iniciado está em primeiro plano. O
analógico esquerdo usa uma zona morta e envia as quatro direções digitais. As
teclas mantidas são liberadas na perda de foco, desconexão ou encerramento do jogo.
Mantenha **teclado** selecionado nas opções de controle do jogo. Configurações
personalizadas de teclado precisam ser ajustadas aos padrões abaixo.

| Controle | Comando | Tecla padrão |
|---|---|---|
| Analógico esquerdo / direcional | Movimento e navegação | Setas |
| ✕ | Pular / nadar | X |
| □ | Atacar / interagir | A |
| ○ | Absorver almas | D |
| △ | Mirar / agarrar | F |
| L1 | Focar / andar devagar | S |
| R1 | Agachar | C |
| Analógico direito (horizontal) | Olhar para esquerda / direita | Num 0 / Ctrl direito |
| L2 / R2 | Sem ação atribuída | — |
| Create | Menu de glifos / confirmar | Enter |
| Options | Pausar / voltar | Esc |

Em janela, uma faixa sobre o jogo mostra os quatro símbolos e destaca os botões
pressionados. Ela não substitui o texto dos tutoriais nem as texturas originais.
Tela cheia exclusiva não oferece suporte à faixa externa. O eixo vertical do
analógico direito, touchpad, giroscópio, vibração e gatilhos adaptáveis não possuem funções nesta versão.
A compatibilidade Bluetooth depende de o Windows expor o controle ao WinMM; a
evidência USB não deve ser estendida automaticamente a Bluetooth ou ao Edge.

## Instalação e preservação

O executável do acompanhante é compilado junto com o instalador e embutido nele.
O build Windows requer Visual Studio Build Tools 2022 ou 2026 com C++ x64. O script
`tools/controller/build.cmd` também pode gerar o acompanhante isoladamente em
`staging/controller-v1`. Ele não abre o jogo nem executa testes durante o build.

O componente instala apenas `sr-dualsense.exe`, com journal próprio
`.soul-reaver-ptbr/controller-journal.json`, SHA-256, trava compartilhada e recusa de
arquivos preexistentes sem propriedade. Não substitui `DINPUT.dll`, executável,
arquivos de conteúdo, configurações de teclado ou saves. **Remover suporte** e
**Restaurar tudo** removem o acompanhante somente se o hash ainda conferir.
**Reparar** atualiza o componente se ele já estiver instalado.

O journal usa um nome próprio porque o runtime de legendas grava o estado ao vivo do
controle em `.soul-reaver-ptbr/controller-runtime.json`; versões antigas gravavam em
`controller-state.json`, que é lido apenas como journal legado quando ainda contém um
registro válido. Um arquivo de status nesse nome nunca bloqueia o diagnóstico.

O acompanhante segue o padrão dos demais módulos: fica em
`modules/controller/` (`controller.json` + `payload/sr-dualsense.exe`), listado em
`modules/bundle.json`. O `sr-dualsense.exe` é reconstruído por `tools/controller/build.cmd`.

Os logs das partidas iniciadas pelo instalador ficam em
`%LOCALAPPDATA%/SoulReaverPTBR/logs/dualsense-<PID>.jsonl` e registram foco, conexão,
botões, eixos e resultado do envio das teclas. Isso prova a leitura e o envio;
a resposta do personagem e dos menus exige observação no jogo.

## Verificação

```powershell
pnpm --dir installer build
cargo build --release -p soul-reaver-mod-installer
staging/controller-v1/sr-dualsense.exe --probe
staging/controller-v1/sr-dualsense.exe --self-test
$env:SRMOD_TEST_EXE = '<pasta-jogo>/kain2.exe'
cargo test -p soul-reaver-mod-installer controller::tests -- --ignored
```

O self-test verifica mapeamento, zona morta, POV e retorno ao estado neutro com
dados sintéticos; não envia teclas nem acessa processos. O teste Rust usa o
executável compatível apenas como bytes de fixture e nunca o executa.

Para diagnóstico local e automação, o próprio instalador aceita as opções CLI:
`--controller-status <pasta>`, `--controller-install <pasta>`,
`--controller-remove <pasta>` e `--controller-launch <pasta>`, além de `--help` e `--version`.
No Windows (mesmo em build release), os modos CLI anexam ao console do processo pai para exibir saídas JSON e erros no terminal.
Somente `--controller-launch` abre o jogo, verificando a trava de operação compartilhada (`operation.lock`); todos usam as mesmas funções do painel.

Na rodada de 16/10/2026, materiais e resultados da avaliação humana ficam em
`validate/18-dualsense/20261016/`. Preservar a instalação Steam e usar uma cópia
isolada para a primeira rodada. Registrar separadamente USB, Bluetooth, foco,
desconexão, resposta no gameplay e legibilidade dos ícones.

Fontes consultadas em 16/10/2026: documentação Microsoft de
[joyGetPosEx](https://learn.microsoft.com/en-us/windows/win32/api/joystickapi/nf-joystickapi-joygetposex)
e [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).
O mapa de teclado foi transcrito do `readme.txt` da cópia clássica local.
