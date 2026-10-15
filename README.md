# Soul Reaver PT-BR Mod

Projeto de mod para **Legacy of Kain: Soul Reaver clássico de PC**, com renderização 4K, tradução dos diálogos e dublagem em português brasileiro com uma voz de IA distinta por personagem.

**Estado atual: planejamento.** Este repositório contém o plano técnico e a decisão de arquitetura do instalador. Ainda não há aplicativo, pacote de mod, release jogável ou comandos de build/teste.

## Instalador planejado

Aplicativo desktop Windows em **Tauri 2 + Rust**, com interface em **React, TypeScript, Vite e Tailwind CSS**:

- Detectar a instalação Steam ou permitir selecionar a pasta do jogo.
- Validar edição, integridade e conflitos antes de aplicar alterações.
- Selecionar gráficos 4K, dublagem PT-BR e legendas.
- Mostrar progresso real e resultado da instalação.
- Verificar, reparar, atualizar e remover o mod preservando saves e backups.

O gerenciador será distribuído como instalador Windows `.exe`; os componentes do mod terão pacotes versionados separados. A implementação e a validação desses recursos estão pendentes.

## Produção das vozes

A geração será local, começando por um piloto com Raziel, Kain e o Ancião. Qwen3-TTS é a primeira opção em avaliação. Unsloth poderá ser usado para ajuste fino se houver necessidade demonstrada no piloto. Quem instalar o mod receberá áudio pronto e não precisará instalar modelos ou ferramentas de IA.

## Plano e evidências

Consulte o [plano completo](docs/PLANO-MOD-4K-PTBR.md) para as evidências da instalação examinada, integração de áudio e vídeos Bink, uso do REA, marcos, riscos e critérios de aceite.

A primeira entrega jogável deverá comprovar uma cena em 4K com três identidades vocais, legendas e sincronização. Ainda não foi testada.

## Conteúdo do repositório

Este projeto não inclui o jogo, seus executáveis, arquivos de dados, vídeos, saves ou modelos de IA. Será necessária uma cópia própria e compatível do jogo. A primeira edição alvo é a versão Steam clássica, AppID 224920; Soul Reaver 2 e a edição Remastered ficam fora do escopo inicial.

O repositório começa privado. O canal de distribuição para terceiros e os termos dos componentes serão definidos antes da publicação de releases.
