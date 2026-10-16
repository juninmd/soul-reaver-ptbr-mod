# Plano de execução — Soul Reaver clássico 100% PT-BR, 3D 4K e vídeo HD

Atualizado em 16/10/2026. Este documento substitui o escopo anterior. Ele é um plano de engenharia e validação; não declara o mod funcional, a campanha completa ou uma distribuição pronta. A instalação Steam original e os saves são entradas imutáveis. Todo teste destrutivo ocorre em cópia isolada, com materiais humanos e capturas em `validate/` (fora do Git).

Diretriz de execução vigente: trabalhar offline e só abrir o jogo após autorização explícita do usuário. Usar subagents GPT-6 Luna em tarefas delimitadas. Builds, verificação de arquivos e hosts offscreen são permitidos; não substituem a rodada no jogo.

### Avanço offline mais recente

- **Fonte de verdade única por módulo:** os candidatos foram promovidos de `staging/packages/local-full-v1` e do material de texturas para a árvore produtiva `modules/` (`voices`, `localization`, `video`, `graphics`, `textures`, `ui` + `bundle.json`). Cada módulo é auto-contido (manifesto + payloads no mesmo diretório). O instalador resolve `modules/` primeiro (override `SRMOD_MODULES`), o vídeo virou componente com journal próprio (`video-state.json`) separado de `localization` (`assets-state.json`), e `validate/` deixou de guardar payload oficial. Testes: core 34, instalador 1, `pnpm build`, empacotador 9/9 e o verificador offline com `--bundle modules` passou preservando executável, save e DLL de terceiros. Mapa e comandos em [`MODULOS.md`](MODULOS.md); evidência em `validate/98-modulos-produtivos/`. Permanece offline: nada foi executado no jogo.
- Instalador por componente concluído no projeto Tauri/Rust: journal próprio para os gráficos 4K (dgVoodoo + patch Hor+ 16:9 com backup do `kain2.exe`), componente externo genérico para texturas HD e interface, ações de instalar/reparar/restaurar e painel de diagnóstico. 23 testes do core passam; `pnpm --dir installer build` e o build do Tauri passam.
- Bundle local completo montado em `staging/packages/local-full-v1` (230 falas, 11 arquivos de localização, wrapper 4K em 3840×2160 em janela) por `tools/build_full_bundle.py`, que verifica o hash de todas as entradas.
- Teste de aceitação offline com cópia limpa reconstruída dos originais: `tools/verify_installer_offline.py` aplica vozes + localização + 4K/widescreen, recusa um `DDraw.dll` estranho, restaura e confirma que o executável voltou ao SHA original, que o save real não mudou e que uma DLL de outro mod sobreviveu. Resultado em `validate/17-instalador/installer-offline-report.json`.
- Lote de texturas HD das 1.287 páginas em produção resumível (`tools/graphics/run_hd_texture_batch.py`). Continua material de revisão: uma POC Frida/WARP no host sintético passou 11 checks com a página #4 após recompilar e fixar os hashes atuais. Isso prova o callback naquele formato sintético, mas ainda não o SRV, UV, alpha ou a integração do loader no jogo; o componente de texturas segue experimental. Evidência: `validate/19-texturas-loader/POC-WARP-2026-10-16.md`.
- Pacote candidato de interface/HUD empacotado como componente instalável experimental (`ui.json` + catálogo NFC de 224 ids + `hd-ui-cache.dll` x86), verificado pelo core real, mas **não integrado ao jogo**: faltam 7 hooks nativos e o mapeamento dos menus/HUD. Evidência: `validate/13-ui-hud-candidato/INTEGRACAO.md`.
- 60 FPS: análise estática localizou o relógio de quadro — integrador com `incremento = delta_ms*4096/33` (magia `0x3E0F83E1`) e quantum `0x1000`, isto é **1 passo = 33,0 ms = 30,303 Hz**, exatamente a taxa medida. Nenhum patch foi aplicado e não há correção defensável sem o gate passo→Present. Evidência: `validate/16-60fps/RELATORIO.md`.
- Renderer x86 de texto dinâmico: UTF-8 estrito, glifos pt-BR, painel, troca e limpeza de legendas testados em D3D11 WARP 3840×2160. O host consultou restauração de RTV e viewport; os outros estados não foram consultados. A integração no jogo permanece pendente.
- As 230 legendas selecionadas geram 266 páginas, todas aceitas pelo verificador GDI do renderer. O texto completo fica preservado em NFC. Tempos de leitura e sincronia ainda exigem runtime.
- Catálogo candidato de UI: 224 IDs, com 161 textos traduzidos, 59 rótulos de tecla, dois símbolos e duas entradas vazias. Preserva os tokens de ícones; tradução e integração aguardam revisão. Não corresponde a 224 textos instalados no jogo.
- Pipeline de vídeo: saída exclusiva, verificação de cadência e contagem, alinhamento explícito de áudio e ASS; teste curto com seis quadros reais passou também pela rota Real-ESRGAN.
- Dez páginas selecionadas por variedade visual em um catálogo offline de 1.287 índices foram ampliadas de 256×256 para 1024×1024 com Real-ESRGAN. O pacote inclui originais RGB, candidatas, RAWs e hashes; bit 15 foi mantido sem interpretação. A página 4 também tem prova direta de readback no cache WARP. A ponte Frida/WARP passa agora no host sintético (11 checks); formato de SRV do loader real, UV, alpha e aparência dentro do jogo continuam sem prova. Este é um lote de revisão, não um pacote completo.
- Renderer de UI/HUD em canvas 3840×2160 implementado, com UTF-8/NFC, cores RGBA, limites e cache de texto. O host offscreen passou; as 266 páginas de legendas também passaram no renderer atualizado. A demonstração usa textos ilustrativos; falta integrar menus, HUD e ícones reais.
- Diagnóstico estático verificou as referências do cálculo de tempo. O global `0xC66F3C` recebe `1` na inicialização; não há justificativa para um patch que apenas o ligue. Os 60 FPS continuam pendentes.

Evidências: `validate/10-candidato-offline/`, `validate/02-legendas-unicode/runtime-v2/`, `validate/09-interface-unicode/`, `validate/12-texturas-hd-candidato/`, `validate/13-ui-hud-candidato/`, `validate/14-texture-catalog/` e `validate/17-instalador/` (instalador por componente e teste offline). O perfil de configuração 60 FPS não resolveu a limitação observada anteriormente; nenhum patch de temporização foi aplicado.

## Resultado pretendido e linha de chegada

Direção dos vídeos em 15/10/2026: o usuário escolheu a amostra Real-ESRGAN em `validate/03-video-1440p/intro-1440p-realesrgan.mp4`, registrada por hash em `content/video-review.json`. Preservar essa configuração para as próximas POCs. A preferência visual não substitui integração HD no player, testes individuais ou escuta integral.

Atualização da direção em 15/10/2026: o usuário aprovou visualmente o trecho 3D em `validate/06-render-4k/trecho-4k.mp4` e pediu pelo menos 60 FPS. A aprovação está fixada pelo hash em `content/graphics-review.json`. Acrescentar 60 FPS reais ao objetivo de renderização; a captura esparsa da primeira POC não comprova desempenho. A próxima POC deve medir apresentação sem o custo de readback e validar física, velocidade de animação, temporizadores e sincronização das falas. Interpolação de vídeo não conta como 60 FPS do jogo.

Entregar uma versão local reproduzível de Legacy of Kain: Soul Reaver clássico com:

- campanha, falas opcionais, repetíveis, narração e diálogos de FMV catalogados e traduzidos para pt-BR natural;
- vozes locais distintas por personagem, mantendo as vozes aprovadas nos IDs 116, 163, 173, 206, 225 e 307; os hashes correspondentes vêm de `content/dialogue-review.json`;
- renderização 3D em 3840×2160, sem esticar a imagem, com texturas novas de personagens e cenários, HUD, menus, dicas e legendas nítidos;
- caracteres acentuados e símbolos corretos em fonte, UI e legendas;
- vídeos tratados em pelo menos 2560×1440, preservando conteúdo 4:3 em 1920×1440 com barras laterais, com trilha PT-BR quando houver fala;
- aplicação, reparo e restauração seguros em cópia de teste, sem exigir IA, CUDA ou conexão no computador do jogador.

“Concluído” exige evidência humana e de runtime por requisito: matriz de cobertura dos 479 slots e eventos de FMV, captura jogável em janela visível, comparação de resolução e proporção, escuta dos áudios, legendas legíveis, teste de instalação/restauração e rollback. Build, catálogo, render sintético, reprodução instrumentada ou pipeline pendente são apenas evidência parcial.

## Escopo e limites

| Dentro | Fora desta etapa |
|---|---|
| Jogo clássico Steam identificado por hash; jogo em janela visível; 3D 4K; texturas externas HD; HUD/menu/legendas; vídeos HD; localização e vozes PT-BR; instalador Tauri/Rust | Executáveis/DAT/BIG/BIK originais, saves, pesos ou referências vocais no Git; exigir IA ao jogador; publicar jogo/mod; alterar a instalação Steam original |
| POCs de competência antes do lote; Unsloth existente como opção de texto e eventual fine-tuning TTS | Chamar Unsloth de restaurador de vídeo; alterar ambiente existente; prometer upscale sem comparar qualidade e compatibilidade |
| Preservação das vozes aprovadas e revisão humana de pt-BR | Remasterização de malha, ray tracing, conteúdo cortado ou outra edição de Soul Reaver |

## Fatos observados e limites atuais

| Área | Evidência atual | Consequência |
|---|---|---|
| Base | `kain2.exe` SHA-256 `9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a`; Steam já está em V6 | Fixar compatibilidade por hash e preservar V6 |
| Vozes | V6 live: 230/479 slots; 249 não substituídos. Isso não é percentual de cobertura da campanha | P0 separa `grunt`, cena, duplicata e evento real |
| FMV | Oito FMV de história estão em teste PT-BR; `verse.bik` é 320×240 e os outros sete são 640×480; existem 11 BIK no total, incluindo logos/créditos visuais | Catalogar cada BIK por quadros, FPS, duração, áudio e runtime; texto de créditos/cartelas em inglês também entra no escopo |
| UI/texto | 159 substituições em 224 strings; há hardcoded, HUD e créditos; `tools/build_dialogue_subtitles.py` remove acentos; `tools/subtitles/runtime.cpp` rejeita não-ASCII; `tools/localize_ui.py` possui bytes altos de fonte/ícones | P1 corrige Unicode ponta a ponta sem omitir strings não substituídas |
| Texturas | Mini-mod STF911 em `staging/texture-mini-review-v1/inspection.json`: 22/1287 atlas, 256×256 ARGB1555, cabeçalho 4096, página 131072; não é HD | P3 prova carregador externo/upload GPU maior, UV/alpha e asset nativo recriado |
| 4K | `validate/06-render-4k/report.json` confirma run10 viewport/draw target 3840×2160, formato GPU 27, 79 amostras e 80 quadros; VFR, sem áudio, textura original e legenda proxy desabilitada | P2 já prova viewport/captura, mas gameplay, efeitos, menus/HUD e texturas HD continuam pendentes |
| Vídeo | Meta: 2560×1440, conteúdo 4:3 1920×1440 com barras | P4 compara Lanczos e Real-ESRGAN em trecho curto (amostra atual: 6 s) |
| Widescreen | `0xEB354` RVA `0xEC354`: float 0.625→0.46875, somente memtest | Validar proporções e câmera em runtime |
| Distribuição | ModDB reconhece chefes Bright; exige crédito e aviso antes da distribuição | Registrar licença/crédito/headsup; não publicar nesta fase |

Fontes e versões ficam em [`REFERENCES.md`](../REFERENCES.md). A validação de áudio existente está em [`VALIDACAO-REINSERCAO-VOZ.md`](VALIDACAO-REINSERCAO-VOZ.md).

## Decisões técnicas

- Usar Rust no core/CLI e Tauri 2 + React/TypeScript/Vite/Tailwind no instalador. O jogador recebe assets prontos.
- Usar dgVoodoo explicitamente em `3840×2160`; `max` não significa 4K e a tela disponível é 1440p. POCs e capturas rodam em janela visível.
- Texturas HD ficam externas; os atlas BIG 256 são referência de formato, não fonte de textura 4K. P3 deve provar carregador externo/upload GPU maior, UV/alpha e assets nativos recriados para HUD/menu.
- Vídeo: trecho curto (amostra atual: 6 s) com áudio preservado, comparação Lanczos/Real-ESRGAN, legenda aplicada depois do upscale; prova offline separada da prova Bink HD.
- Unsloth pode ser usado com o ambiente já instalado para inferência de texto e, somente se uma POC medir ganho, fine-tuning TTS. Não reinstalar, migrar ou exigir Unsloth ao jogador.
- Tradução e síntese passam por revisão humana; ASR é alarme auxiliar e nunca aceita grunhidos como fala PT-BR. Preservar hashes, metadados de direção e arquivos aprovados.

## Milestones e gates

| Etapa | Dono | Depende de | Artefato | Prova de saída |
|---|---|---|---|---|
| P0 | inventário/preservação | nenhuma | matriz, hashes, `steam-before.json` | cópia isolada e eventos reconciliados |
| P1 | texto/fonte/UI | P0 | corpus NFC, fonte-atlas, catálogo de 224 strings | captura com acentos/símbolos |
| P2 | render/runtime | P0 | perfil dgVoodoo, captura 15–30 s, logs | draw target 3840×2160 e proporções |
| P3 | assets/runtime | P2 | pacote externo HD, atlas/UV report | personagens/cenários/HUD em runtime |
| P4 | vídeo/runtime | P0, P2 | pares Lanczos/Real-ESRGAN, 11 manifests | cada BIK medido e executado ou player alternativo HD |
| P5 | localização/voz | P0, P1, P2, P4 | fatia vertical PT-BR, metadados de direção | escuta humana e cena natural |
| P6 | produção/QA | P3, P5 | lotes de áudio, texturas, UI e vídeos | campanha e matriz integral |
| P7 | Tauri/Rust | P6 | instalador, journal, pacote por componente | apply/restore em cópia limpa |

### P0 — Inventário, preservação e matriz de cobertura

Inventariar base, saves, resolução, 479 slots, todos os 11 BIK e 224 strings, incluindo hardcoded, HUD, créditos, texto de cartelas e English credits. Criar matriz por cena/evento com classificação `grunt`, fala de cena, duplicata, não verbal, `cut` (somente com prova) e FMV; registrar acionamento natural, pausa, skip, load e retorno. Produzir `steam-before.json`, hashes e cópia isolada. Gate: zero escrita na Steam original; matriz reconciliada com offsets, eventos e vídeos, sem usar 230/479 como percentual de campanha.

### P1 — Unicode, fontes, UI e legendas

Proibir UTF-8 direto na fonte legada: corrigir bytes altos de fonte/ícones e usar renderer novo/fonte-atlas com Unicode canônico NFC; remover a perda de acentos do gerador de legendas; aceitar caracteres especiais no renderer e em menus/dicas. Gate: corpus pt-BR com `áéíóúãõçÀÉ…`, símbolos e nomes próprios aparece corretamente em janela 1080p/1440p/4K, sem rejeição, truncamento ou fallback ilegível.

### P2 — POC de 3D 4K e câmera

Em janela visível, obter superfície/draw target 3840×2160 na GPU, capturar clipe de 15–30 s e medir frame pacing, HUD, água, transparência, menus e retorno de FMV. Testar dgVoodoo com resolução explícita; testar o offset de câmera 0.625→0.46875 apenas em cópia. Gate: captura e log verificam 3840×2160 e proporção correta; se a tela física for 1440p, registrar que é render interno.

### P3 — Texturas externas HD, personagens/cenários e interface

Expandir a POC STF911 para personagens, cenários, HUD e menus. Medir UV, alpha, upload GPU maior e carregador externo; gerar candidatos HD/4K e assets nativos de interface recriados, sem presumir que o slot BIG 256 aceite 4K. Gate: cena em runtime mostra assets novos sem textura ausente, brilho incorreto ou z-fighting; pacote e restauração conferem hashes.

### P4 — Vídeo HD e trilha PT-BR

Para um trecho curto (amostra atual: 6 s), usar Lanczos como baseline e comparar Real-ESRGAN em 2560×1440 com conteúdo 4:3 em 1920×1440 e barras; aplicar legendas depois do upscale e preservar áudio. Medir nitidez, halos, cadence e tamanho. Testar cada um dos 11 BIK por quadros/FPS/duração/áudio e runtime. Se Bink HD falhar, testar player alternativo mantendo o requisito HD; não reduzir para 480p. Gate: escolher método com evidência; separar prova offline, reprodução e falha `skip/return`.

### P5 — PT-BR integral antes de lotes

Conciliar a matriz de P0, traduzir todos os textos e falas de campanha (sem aceitar grunhido como dedução ASR), revisar pronúncia por personagem, mapear eventos naturais e FMV, preservar vozes aprovadas por hash e criar POC com três personagens. Validar duração/PCM16/22050 mono, volume, silêncio e interrupção. Gate: cobertura de uma fatia vertical (cena natural, repetição, pausa/load/skip, legenda e FMV) aprovada por escuta e runtime; somente então liberar produção em lotes.

### P6 — Produção e QA da campanha

Gerar em lotes retomáveis, com um modelo GPU carregado, metadados e hashes; incluir áudio, texturas HD, HUD/menu e os 11 vídeos HD. Escutar 100% dos áudios finais; testar campanha, opcionais, repetíveis, todos os FMV e saves. Gate: cada evento no escopo tem tradução, personagem, áudio, legenda e evidência de execução; ausências e recursos não verbais ficam classificados.

### P7 — Instalador e homologação local

Aplicar pacotes a cópia limpa com validação do executável compatível e dos source assets por componente, incluindo migrações V6; o executável original permanece preservado. Usar backup transacional, detecção de DLL conflitante, reparo, atualização, remoção e restauração. Gate: instalação interrompida, espaço insuficiente e arquivo alterado posteriormente falham com segurança; saves e Steam original permanecem intactos. Publicação exige decisão posterior, créditos ModDB e artefatos próprios.

## Estratégia de testes e evidências

Cada milestone entrega logs, hashes, capturas e matriz em `validate/`, fora do Git. Testes unitários cobrem parsing, Unicode, manifestos e rollback; integração cobre leitura de slots, fontes, atlas e Bink; runtime cobre jogo em janela visível e eventos naturais. Os comandos existentes (`cargo test -p soul-reaver-mod-core`, `pnpm --dir installer build` e ferramentas em `tools/`) são checks de código, nunca substitutos da prova de runtime. Nenhum resultado será chamado de funcional, homologado ou completo enquanto a evidência correspondente não existir.

## Riscos, rollback e decisões abertas

| Risco | Mitigação | Rollback |
|---|---|---|
| 4K interno não chega à tela ou quebra efeitos | POC visível, captura e comparação 4:3/16:9 | Remover perfil dgVoodoo/patch da cópia |
| Formato de atlas não aceita HD | Preservar slot e testar upload antes do lote | Restaurar atlas original por hash |
| Unicode corrompe fonte/UI | Corpus automatizado + captura humana | Desativar pacote de UI/legendas |
| Bink rejeita vídeo HD ou áudio mixado | Prova offline separada e teste skip/return | Manter vídeo original e registrar pendência |
| Cobertura confundida com contagem de slots | Matriz por evento/cena/FMV | Rejeitar lote incompleto |
| Alteração posterior na base | Hashes, journal e cópia isolada | Restaurar somente estado esperado |

Decisões abertas que bloqueiam promoção: contrato de atlas HD, integração Bink HD, tradução dos eventos desconhecidos e eventual fine-tuning Unsloth. Real-ESRGAN foi escolhido para a amostra comparada; os outros vídeos ainda precisam de avaliação própria. Não há prazos inventados; reestimativa só após métricas de P2, P4 e P5.

## Handoff

Continuar implementações e verificações offline em staging, mantendo `staging/render4k-v1/steam-before.json` como baseline. Preparar a rodada de P1/P2/P4 e aguardar autorização explícita antes de abrir o jogo. Atualizar a matriz com fatos observados; candidatos não são promovidos nem publicados automaticamente.
