# Trabalho neste repositório

## Prioridades

Preservar o jogo original e os saves. Separar fatos observados, propostas e validação em runtime. Não declarar o mod funcional com base apenas em build ou em demonstrações com dados simulados.

## Execução e validação

- Trabalhar offline por padrão. Não abrir o jogo, nem por scripts de captura ou testes automatizados, sem autorização explícita do usuário para a próxima rodada de execução.
- Preparar os ajustes, builds e testes offline antes de solicitar uma rodada de validação no jogo. Quando autorizada, abrir em modo janela, se possível.
- Colocar materiais que dependam de avaliação humana em `validate/`.
- Para economizar tokens, usar subagents GPT-6 Luna nas delegações, com tarefas curtas e responsabilidades separadas.

## Idioma e direção de voz

- Usar sempre português brasileiro (`pt-BR`) nas traduções, legendas, menus e textos de síntese, com vocabulário e construções naturais do Brasil. Preservar o registro e a personalidade de cada personagem.
- Preferir, quando possível, sotaque paulista e/ou mineiro, com traços leves e naturais. Manter consistente a voz de cada personagem e preservar as falas já aprovadas.
- A opção `Portuguese` do Qwen3-TTS não garante a variante brasileira nem o sotaque regional; confirmar pronúncia e atuação por escuta. Não declarar o sotaque validado apenas pelo idioma selecionado ou por ASR.

## Stack e Arquitetura

- **Backend / Core**: Rust (`crates/mod-core`) com validação estrita de hashes SHA-256, journal atômico (`.soul-reaver-ptbr`), travas de processo (`fs2`) e restauração segura. Binário CLI `srmod`.
- **Instalador Desktop**: Tauri 2 (`installer/src-tauri`) com frontend React 19, TypeScript, Vite e Tailwind CSS 4 (`installer/`).
- **Geração e Pipeline de Áudio**: Python 3 com modelo Qwen3-TTS local em CUDA BF16 (`tools/generate_voices.py`) e pipeline de extração de slots de áudio e empacotamento (`tools/audio_pipeline.py`). O jogador recebe apenas os pacotes de áudio prontos.

## Comandos disponíveis

- Testes de integridade e transação do core: `cargo test -p soul-reaver-mod-core` (fixtures isolados, piloto, assets e recusa do antigo pacote com cobertura fictícia 479/479).
- CLI de inspeção/modificação: `cargo run -p soul-reaver-mod-core --bin srmod -- [inspect <game> | apply <game> <manifest> | restore <game>]`.
- Build do frontend do instalador: `pnpm --dir installer build` (TypeScript e Vite).
- Extração de catálogo: `python tools/audio_pipeline.py catalogue --game <pasta-jogo> --output <pasta-saida>`.
- Empacotamento de vozes aprovadas: `python tools/audio_pipeline.py package --game <pasta-jogo> --plan <plano.json> --output <pasta-pacote>`.
- Benchmark e produção de voz na GPU: `python tools/generate_voices.py --plan <plano.json> --model <caminho-modelo> --model-revision <rev> --output <pasta-saida> [--benchmark]`.

## Estrutura

- `Cargo.toml`: Workspace Rust contendo `crates/mod-core` e `installer/src-tauri`.
- `crates/mod-core/`: Biblioteca Rust e binário CLI `srmod`.
- `installer/`: Aplicativo desktop Tauri 2 com interface React/TypeScript/Tailwind.
- `tools/`: Scripts de catálogo, empacotamento e síntese TTS offline.
- `docs/`: `PLANO-MOD-4K-PTBR.md` e `VALIDACAO-REINSERCAO-VOZ.md`.
- `REFERENCES.md`: Registro de ferramentas, repositórios e documentação citada.
- `staging/`: Diretório de trabalho local fora do controle de versão para benchmarks, catálogos e pacotes de teste.

## Limites e Segurança

- Não adicionar executáveis do jogo, arquivos DAT/BIG/BIK, saves, extrações, pesos de IA, referências vocais de terceiros ou chaves ao Git.
- Manter backups, staging e instalação de teste fora da cópia original da Steam.
- Não sobrescrever DLLs de outros mods nem restaurar arquivos alterados posteriormente sem conferir hashes e propriedade.
- Não embutir tokens GitHub no instalador para acessar releases privadas.
- A criação deste repositório não autoriza disponibilizar publicamente o jogo ou publicar releases do mod.
- Ler o estado atual do Git antes de alterar branches; preservar trabalho alheio.

<!-- base-actions-main-policy -->
## GitHub Actions — padrão obrigatório (@main)

- Referencie as actions internas sempre pelo branch, nunca por SHA:
  - `uses: juninmd/base-actions/<action>@main`
  - `uses: juninmd/base-actions/.github/workflows/<arquivo>.yml@main`
- Não fixe `@<sha>` em `juninmd/base-actions`: a atualização é centralizada no
  `main` e passa a valer no próximo run.
- PRs cujos checks não iniciam por billing/spending limit são mesclados pelo bot central
  `juninmd/base-actions/.github/workflows/auto-merge-billing-blocked.yml`.
  Para impedir o merge automático de um PR, aplique a label `do-not-merge`.