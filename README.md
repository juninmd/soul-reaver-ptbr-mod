# Soul Reaver PT-BR Mod

Projeto de mod para **Legacy of Kain: Soul Reaver clássico de PC** (Steam AppID 224920), com renderização 4K, tradução dos diálogos e dublagem em português brasileiro com vozes de IA distintas por personagem.

## Status da Implementação

Auditoria atualizada em 16/10/2026: o projeto está **em andamento e não homologado**. A matriz tem 479 slots; 230 são candidatos de fala de cena, 215 permanecem desconhecidos e 34 estão em duplicatas. Seis takes foram aprovados por escuta (116, 163, 173, 206, 225 e 307), mas isso não prova cobertura total, disparo natural ou sincronia. Os detalhes e limites estão em [`validate/00-plano/STATUS-GERAL.md`](validate/00-plano/STATUS-GERAL.md).

A rota Unicode de legendas foi exercitada em host offline (266 páginas), mas o pacote V6 atualmente registrado usa 230 linhas ASCII sem diacríticos; não há prova de legendas acentuadas integradas no jogo. O catálogo HD contém 1.287 páginas candidatas ampliadas a 1024×1024, a ponte Frida/WARP atual passou 11 checks sintéticos, mas a ligação com o loader do jogo segue sem prova. Renderer de HUD/menus e catálogo seguem sem ligação demonstrada às chamadas reais do jogo. O perfil/captura 3840×2160 prova apenas preparação offline, não gameplay em 4K.

Para FMV, há um candidato BIK completo em 2560×1440 (`crylogo`) decodificado offline. O `intro` tem quadros ampliados e composição pronta, mas o BIK final não foi produzido; os demais vídeos HD seguem pendentes. Playback e integração no jogo não foram validados. 60 FPS também não foi alcançado: as evidências atuais indicam cerca de 30,3 Presents/s e passo fixo de ~33 ms.

O instalador tem fluxos offline em fixtures isoladas. Na atualização de 16/10, a restauração passou a acumular erros por componente e a inspeção deixou de ocultar falhas; os testes do core (31/31) e do novo caso unitário do instalador (1/1) passaram. Isso não homologa uso na instalação Steam. O estado atualizado e o histórico de validações ficam em [`validate/00-plano/`](validate/00-plano/).

1. **Validação de Reinserção em Runtime**:
   - A tabela exata de 479 entradas de áudio (`voices.dat`) no executável `kain2.exe` foi decodificada e conferida byte a byte.
   - O índice 291 (fala de Raziel com Dumah) foi reinserido e reproduzido em runtime instrumentado com buffers idênticos capturados e saída de áudio confirmada.
   - Veja [`docs/VALIDACAO-REINSERCAO-VOZ.md`](docs/VALIDACAO-REINSERCAO-VOZ.md).

2. **Pipeline de Áudio e Extração**:
   - Ferramenta [`tools/audio_pipeline.py`](tools/audio_pipeline.py) extrai integralmente os 479 slots de áudio com hashes conferidos e gera catálogos.
   - Ferramenta de empacotamento compila apenas áudios aprovados, alinhados à taxa de 22.050 Hz PCM16 com silêncios ajustados, sem modificar executáveis ou DATs fora dos limites.

3. **Síntese Local e Benchmark na GPU**:
   - Ferramenta [`tools/generate_voices.py`](tools/generate_voices.py) executa geração offline com Qwen3-TTS em CUDA BF16.
   - Benchmark comparativo executado na RTX 4060 Ti para lotes de 1, 2 e 4 falas com medição de VRAM, RTF e persistência atômica.

4. **Núcleo de Gerenciamento e Segurança em Rust (`crates/mod-core`)**:
   - Biblioteca Rust e ferramenta CLI `srmod`.
   - Gerenciamento transacional com journal de estados (`.soul-reaver-ptbr`), travas de processo (`fs2`), proteção contra links e junctions.
   - Criação e validação automática de backup do `voices.dat` original, com garantia de integridade SHA-256 e restauração segura.
   - Testes de transação com fixture isolado e piloto real. Regressão que recusa cobertura fictícia com áudio original e corrige a contagem de journals legados.

5. **Dublagem e legendas em produção**:
   - Há 479 slots na base original, incluindo falas, vocalizações e material não utilizado. A matriz atual tem 230 candidatos de fala de cena, mas não há cobertura total confirmada; seis takes estão aprovados por escuta.
   - Existe evidência histórica de runtime para o piloto da entrada 291 e trechos iniciais. Ela não comprova disparo e sincronia do conjunto atual nem cobertura das demais cenas.
   - O catálogo atual de FMV ainda tem associação de falas e eventos naturais pendentes. Para qualidade HD, apenas `crylogo` tem candidato completo 2560×1440 decodificado offline; veja o status geral para detalhes.
   - O pacote V6 registrado usa TSV ASCII sem acentos. A rota Unicode foi exercitada em host offline, mas ainda não foi comprovada no renderer do jogo. JSON/SRT soltos não comprovam integração.
6. **Aplicativo Instalador Desktop (`installer/`)**:
   - Frontend em React 19, TypeScript, Vite e Tailwind CSS 4.
   - Identidade **Nosgoth**: ilustração original, bronze e luz espectral; janela sem moldura nativa do Windows, com controles próprios.
   - Backend nativo em Tauri 2 com comunicação tipada via IPC e streaming de eventos de progresso.
   - Seleção automática da biblioteca Steam ou seleção manual com detecção e inspeção de integridade.
   - Instalação por componente com journal e verificação de hash: dublagem, localização (menus, vídeos e legendas), 4K dgVoodoo + Hor+ 16:9 e os componentes externos experimentais (texturas HD, interface/HUD).
   - Ações de **Instalar**, **Reparar** (reaplica de forma idempotente) e **Restaurar tudo**, além de um painel de **Diagnóstico** que reporta hash do executável, base compatível, jogo fechado e o estado de cada componente.
   - Prova offline numa cópia isolada em `tools/verify_installer_offline.py`; roteiro de rodada no jogo em `validate/17-instalador/ROTEIRO-VALIDACAO-JOGO.md`.

## Como Executar

### Executar o Instalador Desktop (Release)

A interface Nosgoth organiza a instalação em **A jornada**, **Componentes**,
**Restauração** e **Diagnóstico e controle**. A revisão exibe as escolhas antes
de aplicar; o progresso representa a etapa real informada pelo Rust. Pausa e
parada são cooperativas, e o fechamento é protegido durante operações de escrita.
Veja [interface, compilação e validação](docs/INSTALADOR-NOSGOTH.md).

O instalador inclui um painel **Controle DualSense**, com detecção, instalação
segura, mapa dos botões e **Jogar com DualSense**. Os ícones aparecem numa faixa
sobre o jogo em janela. O componente usa o teclado padrão e tem remoção própria;
veja [controles, limites e validação](docs/DUALSENSE.md).

```powershell
& "target\release\soul-reaver-mod-installer.exe"
```

### Testes do Core (Rust)

```powershell
cargo test -p soul-reaver-mod-core
```

### CLI de Modificação

```powershell
cargo run -p soul-reaver-mod-core --bin srmod -- inspect "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- components "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- apply "<caminho-do-jogo>" "<caminho-manifesto>"
cargo run -p soul-reaver-mod-core --bin srmod -- restore "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- assets-apply "<caminho-do-jogo>" "<assets.json>" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- assets-restore "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- graphics-apply "<caminho-do-jogo>" "<pasta-graphics>" [widescreen]
cargo run -p soul-reaver-mod-core --bin srmod -- graphics-restore "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- textures-apply "<caminho-do-jogo>" "<textures.json>" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- textures-restore "<caminho-do-jogo>"
cargo run -p soul-reaver-mod-core --bin srmod -- ui-apply "<caminho-do-jogo>" "<ui.json>" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- ui-restore "<caminho-do-jogo>"
```

Na CLI, `apply`/`restore` operam as vozes; `assets-*` a localização; `graphics-*` o
wrapper dgVoodoo 4K e o patch Hor+ 16:9; `textures-*` e `ui-*` os componentes externos
experimentais. Cada componente tem journal próprio e backup verificado. O aplicativo
desktop coordena todos em uma única operação por componente.

### Montar a árvore produtiva e testar offline

A fonte de verdade do instalador é `modules/` (uma pasta auto-contida por
módulo: dublagem, localização, vídeos, 4K, texturas, interface). Detalhes do
mapa módulo → componente em [`docs/MODULOS.md`](docs/MODULOS.md).

```powershell
python tools/organize_modules.py --dry-run   # plano
python tools/organize_modules.py             # promove candidatos para modules/

python tools/verify_installer_offline.py `
  --steam "D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver" `
  --bundle modules --work staging/install-test-modules `
  --srmod-bin target/debug/srmod.exe
```

O verificador reconstrói uma cópia limpa a partir dos originais, aplica os módulos,
testa conflito de wrapper, restaura e confere que o executável, o save e uma DLL de outro
mod permaneceram intactos. Ele nunca abre o jogo nem toca a Steam.

### Build do Instalador Desktop

```powershell
pnpm --dir installer build
```

## Documentação e Referências

- [`docs/PLANO-MOD-4K-PTBR.md`](docs/PLANO-MOD-4K-PTBR.md): Plano mestre, arquitetura, marcos de entrega e critérios de aceite.
- [`docs/MODULOS.md`](docs/MODULOS.md): Fonte de verdade única do instalador — árvore `modules/`, mapa módulo → componente e verificação offline.
- [`docs/VALIDACAO-REINSERCAO-VOZ.md`](docs/VALIDACAO-REINSERCAO-VOZ.md): Evidências da reinserção de áudio e limites de execução.
- [`REFERENCES.md`](REFERENCES.md): Lista de documentações oficiais, ferramentas e referências técnicas consultadas.

## Conteúdo do Repositório

Este projeto não inclui o jogo original, seus executáveis, arquivos DAT/BIG/BIK, saves ou pesos de modelos de IA. É necessária uma cópia própria e compatível do jogo da edição Steam clássica.
