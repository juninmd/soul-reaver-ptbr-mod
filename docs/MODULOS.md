# Módulos produtivos do instalador

Atualizado em 16/10/2026. Este documento fixa a **fonte de verdade única** do
instalador: uma pasta auto-contida por módulo, em `modules/`. O instalador lê
`modules/` diretamente; `staging/` é área de trabalho e `validate/` mostra
andamento — nenhum dos dois guarda arquivo oficial.

## Regra de ouro

- `modules/<módulo>/` — arquivo oficial **candidato** de produção. Manifesto e
  payloads no **mesmo diretório** (o core recusa payload fora da pasta do
  manifesto, por segurança).
- `staging/` — área de trabalho local (benchmarks, catálogos, pacotes antigos).
  Nunca é origem de instalação.
- `validate/` — evidência de andamento e revisão humana (relatórios, HTML,
  capturas). **Não** guarda payload oficial.
- `modules/` está no `.gitignore`: contém binários derivados do jogo/IA, que não
  vão para o Git. A árvore é reproduzível por `tools/organize_modules.py`.

## Árvore e mapa módulo → componente

| Pasta | Manifesto | Componente do core | Conteúdo |
|---|---|---|---|
| `modules/voices/` | `manifest.json` | voices (`.soul-reaver-ptbr/state.json`) | 230 `voice-XXXX.pcm` (dublagem PT-BR) |
| `modules/localization/` | `assets.json` | assets — journal `assets-state.json` | Menus/dicas, legendas, proxy e, quando incluído no manifesto, `asset-bigfile.dat` com o fundo de Nosgoth |
| `modules/video/` | `video.json` | assets — journal **`video-state.json`** | 8 `asset-*.bik` (`intro`, `chrono3/5/7/9/11/13`, `verse`) |
| `modules/graphics/` | — | graphics | `DDraw.dll`, `D3DImm.dll`, `dgVoodoo.conf` (4K + Hor+ 16:9) |
| `modules/textures/` | `textures.json` | external `TEXTURES` — journal `textures-state.json` | 1.287 `payload/page-XXXX.raw` (HD 1024²) — **experimental** |
| `modules/ui/` | `ui.json` | external `UI` — journal `ui-state.json` | `payload/hd-ui-cache.dll`, `payload/ui-ptbr.bin` — **experimental** |
| `modules/controller/` | `controller.json` | external `CONTROLLER` — journal `controller-state.json` | `payload/sr-dualsense.exe` (companheiro DualSense) |
| `modules/bundle.json` | índice | — | lista de módulos, resolução, marcações `experimental` |

Legendas e vídeos têm pastas e journals separados: a localização cobre menus,
dicas, legendas e o proxy; os vídeos (BIK) são um componente próprio, o que
permite restaurar um sem mexer no outro.

O [fundo do menu Nosgoth](MENU-NOSGOTH.md) usa o componente de localização.
Ele substitui somente a imagem nativa `title1.pti` dentro de uma cópia verificada
de `bigfile.dat`; o pacote local continua fora do Git.

## Como o instalador resolve

`find_bundle()` no backend Tauri procura `modules/` primeiro (override por
`SRMOD_MODULES`), com fallback legado para `staging/packages/*`. A aplicação, o
reparo e a restauração operam cada módulo pelo seu journal verificado.

Comandos equivalentes na CLI (`srmod`):

```powershell
cargo run -p soul-reaver-mod-core --bin srmod -- apply "<jogo>" "modules/voices/manifest.json"
cargo run -p soul-reaver-mod-core --bin srmod -- assets-apply "<jogo>" "modules/localization/assets.json" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- assets-apply "<jogo>" "modules/video/video.json" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- graphics-apply "<jogo>" "modules/graphics" widescreen
cargo run -p soul-reaver-mod-core --bin srmod -- textures-apply "<jogo>" "modules/textures/textures.json" "<backup-externo>"
cargo run -p soul-reaver-mod-core --bin srmod -- ui-apply "<jogo>" "modules/ui/ui.json" "<backup-externo>"
```

> O componente de vídeo é aplicado pelo mesmo motor de assets, com journal
> próprio (`video-state.json`). A CLI demonstra o caminho por `assets-apply`;
> o aplicativo desktop seleciona o componente de vídeo automaticamente.

## Reconstruir a árvore

`tools/organize_modules.py` promove os candidatos de `staging/packages/local-full-v1`
e do material de texturas para `modules/`:

```powershell
python tools/organize_modules.py --dry-run   # mostra o plano
python tools/organize_modules.py             # aplica (recusa sobrescrever)
```

Ele é one-shot: recusa rodar novamente se os destinos já existem (não sobrescreve).
Para reconstruir do zero, esvazie `modules/` de forma explícita antes.

## Verificação offline

`tools/verify_installer_offline.py --bundle modules` reconstrói uma cópia limpa
dos originais, aplica os módulos, testa conflito de wrapper, restaura e confirma
executável, save e DLL de terceiros intactos. Não abre o jogo nem escreve na
Steam. Resultado mais recente: `validate/98-modulos-produtivos/`.

## Limites

- "Oficial" significa **candidato de produção local**, não publicação. Nada foi
  homologado em runtime.
- Texturas e interface seguem **experimentais**: o carregador no jogo não é
  comprovado.
- A cobertura de dublagem é de slots físicos (230/479), não de diálogos da
  campanha.
