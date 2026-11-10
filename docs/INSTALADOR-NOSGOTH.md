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

| Caminho | Responsabilidade |
| --- | --- |
| `installer/src/app/` | Casca do aplicativo (`app.tsx`), navegação e estado derivado das operações |
| `installer/src/screens/` | Uma tela por arquivo: jornada, componentes, operação, restauração e diagnóstico |
| `installer/src/dialogs/app-dialogs.tsx` | Conteúdo de cada confirmação exibida no diálogo modal |
| `installer/src/components/` | Peças reutilizadas: barra de título, navegação, local do jogo, avisos, modal, cena de Nosgoth, painel DualSense e ícones |
| `installer/src/installer/model.ts` | Tipos do IPC e regras puras: disponibilidade, escolhas efetivas e progresso por etapa |
| `installer/src/installer/ipc.ts` | Fronteira tipada com os comandos Rust |
| `installer/src/installer/use-installer.ts` | Eventos, consultas, travas e ciclo das operações |
| `installer/src/styles/` | `tokens.css` (paleta, tipografia, tempos), `base`, `shell`, `components`, `scene`, `screens`, `dialogs` e `motion` |
| `installer/public/nosgoth.svg` | Ilustração original, sem dependência de rede |
| `installer/src-tauri/src/commands.rs` | Comandos IPC; trabalho bloqueante fora da thread da interface |
| `installer/src-tauri/src/transactions.rs` | Ordem e pré-validação de instalar, restaurar e reparar |
| `installer/src-tauri/src/diagnostics.rs` | Relatório de passagem única: estado do jogo, diagnóstico e controle |
| `installer/src-tauri/src/operation.rs` | Operação única em andamento, pausa/cancelamento e eventos de progresso com taxa limitada |
| `installer/src-tauri/src/bundle.rs`, `detect.rs`, `paths.rs` | Pacote e seus layouts, bibliotecas Steam e pastas de backup/log |
| `installer/src-tauri/src/controller.rs`, `game_launch.rs` | Acompanhante DualSense e abertura do jogo na pasta selecionada |
| `installer/src-tauri/src/cli.rs` | Modos de linha de comando |
| `installer/src-tauri/tauri.conf.json`, `capabilities/default.json` | Janela e permissões dos controles |

A interface pede ao backend um único relatório por atualização
(`inspect_installation`); o estado do jogo, o diagnóstico e o controle derivam da
mesma inspeção dos arquivos. A descrição do pacote é verificada ao abrir, em
**Atualizar diagnóstico** e em **Verificar pacote novamente**; a inspeção feita
ao fim de uma operação reutiliza a última descrição verificada. A instalação
confere cada payload outra vez antes de gravar.

`tauri.conf.json` define uma Content-Security-Policy restrita: scripts, estilos e
imagens apenas do próprio aplicativo, conexões apenas para o IPC do Tauri, sem
`unsafe-inline` nem `unsafe-eval`. O verificador da interface serve o documento com
essa mesma política, e um recurso bloqueado aparece como aviso na janela.

A troca de telas usa apenas CSS. A API View Transitions foi testada e removida:
`document.startViewTransition` derrubava o processo no WebKitGTK 2.52.

O pacote é procurado em `SRMOD_MODULES`/`SRMOD_REPO`, depois ao redor do executável
(até três níveis, o que alcança a raiz do repositório a partir de `target/<perfil>/`)
e por fim ao redor do diretório de trabalho. Nenhum caminho de máquina é fixo.

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

Esse verificador usa Playwright e Chromium **já instalados** (módulo `playwright`
resolvível pelo Node ou registrado em `%LOCALAPPDATA%/ms-playwright/.links`); não
baixa dependências. Ele executa o
frontend real com um transporte Tauri controlado, apenas no processo de teste.
O relatório identifica o backend simulado. Isso verifica a interface e os
argumentos IPC, sem comprovar por si só a aplicação real de arquivos.

No Linux, `tools/verify_installer_native.sh` executa o binário real (backend Rust,
frontend embutido e WebKitGTK) sob Xvfb, percorre telas e diálogos com cliques e
teclado sintéticos e falha se o processo encerrar. Ele roda sem pacote e sem pasta
de jogo, portanto não inspeciona nem grava arquivos, e não substitui a rodada no
Windows.

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
