# Instalador Nosgoth

Implementação da identidade visual aprovada a partir do protótipo em
`validate/95-identidade-instalador/`. Os materiais de avaliação e os relatórios
desta integração ficam em `validate/96-identidade-implementada/`.

## Experiência

- **A jornada**: ilustração dos pilares, apresentação do projeto e instalação detectada.
- **Componentes**: disponibilidade e cobertura obtidas do pacote real. Gráficos e
  widescreen têm escolhas próprias; widescreen depende dos gráficos selecionados.
  Componentes experimentais permanecem opcionais e identificados.
- **Revisão**: destino, escolhas efetivas e confirmação antes de instalar.
- **Operação**: progresso por etapa enviado pelo Rust. Uma etapa em 100% não
  equivale à conclusão da operação. Pausa, retomada e parada usam o controle
  cooperativo existente no core. Após a instalação bem-sucedida, **Abrir jogo**
  inicia a cópia selecionada por clique explícito, sem exigir DualSense. O botão
  aguarda a verificação final e fica desabilitado se o jogo estiver aberto.
  Falhas ao abrir são exibidas e permitem tentar novamente; não alteram o resultado
  da instalação. O jogo nunca abre automaticamente ao concluir uma operação.
- **Restauração**: confirmação para reparar ou restaurar componentes gerenciados.
  Após falha ou interrupção, a interface atualiza o diagnóstico e informa que
  componentes já aplicados podem permanecer instalados.
- **Diagnóstico e controle**: estado dos componentes, hash do executável e suporte
  DualSense. Instalação, remoção e abertura do jogo possuem confirmações próprias.
- **Modos de linha de comando**: o executável do instalador aceita opções CLI para
  verificação automatizada e diagnósticos (`--controller-status <pasta>`,
  `--controller-install <pasta>`, `--controller-remove <pasta>`, `--controller-launch <pasta>`,
  `--help` e `--version`). Em builds release no Windows, o processo anexa ao console pai
  (`AttachConsole`) para emitir mensagens no terminal em vez de silenciar saídas.
  `--controller-launch` respeita a trava de operação compartilhada (`operation.lock`)
  para impedir inicializações enquanto o GUI aplica componentes.

A janela usa `decorations: false`, `shadow: false`, 1240 × 800 como tamanho
inicial e 860 × 680 como mínimo. A barra possui arraste e controles de minimizar,
maximizar/restaurar e fechar. O fechamento pelo botão, Alt+F4 ou barra de tarefas
é interceptado durante uma escrita; a interface oferece uma parada segura e
permite fechar após a operação terminar.

Os estados de carregamento, pacote ausente, pasta incompatível, jogo em execução,
falha, interrupção e conclusão são distintos. Falhar a atualização do diagnóstico
após uma operação bem-sucedida não reclassifica a aplicação como falha.
Se a própria inspeção falhar, a aplicação continua bloqueada e a opção de solicitar
recuperação permanece acessível. A confirmação explica que só registros e backups
válidos permitem restaurar; a decisão final e a recusa de conflitos pertencem ao Rust.

## Fontes

| Arquivo | Responsabilidade |
| --- | --- |
| `installer/src/App.tsx` | Navegação, telas, diálogos e controles de janela |
| `installer/src/use-installer.ts` | IPC, eventos, consultas e ciclo das operações |
| `installer/src/installer-model.ts` | Tipos, disponibilidade, escolhas efetivas e progresso por etapa |
| `installer/src/dualsense-panel.tsx` | Apresentação do suporte ao controle e mapeamento |
| `installer/src/icon.tsx` | Ícones vetoriais |
| `installer/src/tokens.css`, `nosgoth.css`, `index.css` | Paleta, composição aprovada e estados da interface |
| `installer/public/nosgoth.svg` | Ilustração original, sem dependência de rede |
| `installer/src-tauri/src/main.rs` | Comandos existentes; consultas pesadas executadas em `spawn_blocking` |
| `installer/src-tauri/src/game_launch.rs` | Validação do executável e abertura na pasta selecionada, sem exigir controle |
| `installer/src-tauri/tauri.conf.json`, `capabilities/default.json` | Janela e permissões dos controles |

As regras de integridade, propriedade, backup e restauração continuam no core.
Não há dados demonstrativos, temporizadores de progresso simulado nem caminhos
de jogo fixados no frontend de produção. Não há jogo aberto automaticamente.

## Compilar

Com as dependências locais já instaladas, na raiz do repositório:

```powershell
pnpm --dir installer build
cargo build --offline --locked --release -p soul-reaver-mod-installer --target-dir target
& 'target/release/soul-reaver-mod-installer.exe'
```

O executável usa os assets frontend embutidos na compilação. Recompile o frontend
antes do Rust após alterar as telas.

## Verificar

```powershell
cargo test --offline --locked -p soul-reaver-mod-core -p soul-reaver-mod-installer
cargo fmt -p soul-reaver-mod-installer --check
```

Para a regressão da interface, inicie a build de produção local:

```powershell
pnpm --dir installer exec vite preview --host 127.0.0.1 --port 1496 --strictPort
```

Em outro terminal:

```powershell
node tools/verify_installer_ui.mjs
```

Esse verificador usa Playwright e Chromium **já instalados** e registrados em
`%LOCALAPPDATA%/ms-playwright/.links`; não baixa dependências. Ele executa o
frontend real com um transporte Tauri controlado, apenas no processo de teste.
O relatório identifica o backend simulado. Isso verifica a interface e os
argumentos IPC, sem comprovar por si só a aplicação real de arquivos.

A rodada nativa separada usa WebView2, o backend Rust e uma fixture em `staging/`.
Os relatórios registram exatamente quais componentes foram aplicados/restaurados
e os hashes conferidos. Não se deve usar nenhum desses resultados como prova de
cobertura, qualidade ou funcionamento do mod no jogo.

## Compatibilidade com registros antigos

Instalações anteriores podiam registrar localização e vídeos juntos em
`assets-state.json`. O instalador reconhece esse formato e apresenta os dois
componentes separadamente, mantendo as verificações de arquivos e backups.
A inspeção não modifica esse registro. Na próxima operação de aplicação ou
restauração desses componentes, o core preserva uma cópia exata do registro antigo
e separa os registros de localização e vídeo sob a trava compartilhada.
Registros divergentes, arquivos alterados e backups inválidos continuam impedindo
a operação, preservando os arquivos.

A regressão do erro `Localização incompatível: intro.bik` foi verificada com
restauração dos três arquivos de localização e dos oito vídeos numa cópia isolada,
além da inspeção somente leitura da instalação Steam na interface Release.
Evidências locais: `validate/97-legacy-assets/`.
