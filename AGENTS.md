# Trabalho neste repositório

## Prioridades

Preservar o jogo original e os saves. Separar fatos observados, propostas e validação em runtime. Não declarar o mod funcional com base apenas em build ou em demonstrações com dados simulados.

## Stack decidida

Instalador previsto: Tauri 2 com Rust, React, TypeScript, Vite e Tailwind CSS. Geração de voz local no ambiente de produção; jogador recebe áudios prontos. Unsloth é opcional para experimentos de ajuste fino.

## Comandos disponíveis

Este repositório contém somente documentação e configuração Git inicial. Ainda não há manifests, lockfiles, scripts de build, testes ou CI. Não apresentar comandos de desenvolvimento como existentes antes do scaffold e de sua verificação.

## Estrutura

- `docs/PLANO-MOD-4K-PTBR.md`: escopo, arquitetura proposta, evidências, marcos e critérios de aceite.
- `installer/`: destino planejado para o aplicativo; ainda não existe.
- O runtime de integração do jogo será x86; isso não obriga o instalador desktop a ser x86.

## Limites

- Não adicionar executáveis do jogo, arquivos DAT/BIG/BIK, saves, extrações, pesos de IA, referências vocais de terceiros ou chaves ao Git.
- Manter backups, staging e instalação de teste fora da cópia original da Steam.
- Não sobrescrever DLLs de outros mods nem restaurar arquivos alterados posteriormente sem conferir hashes e propriedade.
- Não embutir tokens GitHub no instalador para acessar releases privadas.
- A criação deste repositório não autoriza disponibilizar publicamente o jogo ou publicar releases do mod.
- Ler o estado atual do Git antes de alterar branches; preservar trabalho alheio.

## Convenções

Não existe código de implementação para estabelecer exemplos de estilo. Ao criar o scaffold, derivar comandos e convenções dos arquivos reais e atualizar este documento. Textos de interface e documentação para usuários serão em português brasileiro.
