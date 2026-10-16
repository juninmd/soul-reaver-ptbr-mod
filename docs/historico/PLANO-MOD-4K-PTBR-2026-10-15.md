# Plano: Soul Reaver clássico em 4K com dublagem PT-BR local

Inspeção inicial: 14/10/2026. Atualização em 15/10/2026: o candidato local na Steam contém 230 entradas dubladas, menus PT-BR, oito vídeos de história em português e legendas dos diálogos incluídos. Instalação/restauração nativas e preservação do save foram verificadas. A campanha permanece parcial. A abertura e o tutorial tiveram acionamento natural; os outros vídeos foram reproduzidos mediante instrumentação, sem comprovação de seus acionamentos naturais. Consulte a [validação de reinserção](VALIDACAO-REINSERCAO-VOZ.md) para evidências e limites. As seções de planejamento abaixo conservam propostas anteriores e não constituem prova de implementação ou de runtime.

Decisão de 14/10/2026: manter o projeto privado no GitHub em `juninmd/soul-reaver-ptbr-mod` e desenvolver um instalador desktop em Tauri 2, React, TypeScript, Vite e Tailwind CSS. Implementação autorizada em 15/10/2026; a primeira entrega será um pacote piloto local com uma fala aprovada, catálogo completo de `voices.dat`, produção em lotes e aplicação/restauração verificadas numa cópia de teste. Isso não equivale à dublagem completa nem à publicação de uma release.

## Objetivo e escopo

Criar um mod para a instalação Steam clássica de Legacy of Kain: Soul Reaver, com renderização 3D em 3840×2160, apresentação sem distorção, tradução dos diálogos efetivamente presentes na campanha e dublagem em português brasileiro com uma voz de IA distinta e consistente por personagem. Incluir falas em vídeos, narração, diálogos opcionais e falas repetíveis que tenham conteúdo verbal. Acrescentar legendas PT-BR sincronizadas como instrumento de acessibilidade e conferência.

A preferência confirmada é gerar as vozes localmente. O jogador receberá os áudios prontos: não precisará executar IA, ter GPU NVIDIA ou manter conexão para jogar. Downloads iniciais de ferramentas e modelos serão necessários no ambiente de produção; a síntese deverá funcionar offline depois disso.

Ficam fora da primeira versão: remasterização de modelos e texturas, ray tracing, refazer animações labiais, Soul Reaver 2, a edição Remastered e conteúdo cortado que não participa da campanha desta edição. Upscale dos vídeos é uma expansão opcional; traduzir suas falas faz parte do escopo principal. A tradução de menus e tutoriais escritos passou a fazer parte da correção solicitada, sem ser confundida com cobertura dos diálogos.

## Evidências locais

| Item | Constatação |
|---|---|
| Instalação | Steam AppID 224920; manifesto local com buildid 23388 e idioma english |
| Executável | kain2.exe, PE x86, 1.080.832 bytes; sem versão legível nos metadados consultados |
| Recursos | voices.dat, music.dat, bigfile.dat, textures.big, locals.pc e patch001.dat |
| Vídeos | 11 arquivos .bik; todos têm vídeo Bink e uma faixa de áudio estéreo a 44.100 Hz |
| Intro | intro.bik: 640×480, aproximadamente 210,94 segundos |
| Outros vídeos | chrono3/5/7/9/11/13 em 640×480; créditos, logos e verse.bik em 320×240 |
| Hardware | Ryzen 7 5700X, RTX 4060 Ti com 16.380 MiB reportados por nvidia-smi, aproximadamente 32 GB de RAM |
| Exibição atual | 2560×1440; capacidade física máxima do monitor não foi verificada |
| Ferramentas encontradas | FFmpeg, ffprobe, uv, Python 3.14 e Node; rea não foi encontrado no PATH |
| Unsloth/CUDA | Python 3.13.15 do Studio, Torch 2.10.0+cu130 e BF16/CUDA validados; dependências Qwen em overlay local, sem reinstalar nem alterar o ambiente compartilhado |
| Formato das vozes | PCM16 little endian, mono, 22.050 Hz; tabela de 479 entradas no executável, com cobertura exata de 152.028.822 bytes (57,456 min) |
| Reinserção | Índice 291, offset 33.503.518, tamanho 279.842 bytes (6,345624 s); cinco buffers reais idênticos ao intervalo modificado e fala PT-BR capturada por loopback |
| Limite da prova | Acionamento instrumentado da fila de vozes na abertura/tela inicial; cena natural, pausa, skip, load e demais personagens ainda pendentes |

A presença do readme do patch 1.2 não comprova a versão efetiva do executável. Fixar compatibilidade pelo hash, não pelo nome do arquivo.

SHA-256 da base inspecionada:

```text
kain2.exe    9793031080E606075D7AF51D7232C12494449A87FE120675E0C80C318C89A30A
voices.dat   E2A193B62F9723F5F477F705C53A56F895375CE2D980D276D0D0FCEEB2645DF5
bigfile.dat  30295BB8BDD059A3001F4B30D68973FD2E6A3AE50EA444087C8A17E94ADEB035
locals.pc    2244304CBF1D89F7AAEE44C534CF185C0FFD037272DEEE909247727BE1D54D84
```

## Caminho técnico escolhido

### Renderização

1. **Wrapper dgVoodoo2 (v2.87.5 x86)**:
   - Intermedeia as chamadas originais DirectDraw / Direct3D 6 legadas do `kain2.exe` para Direct3D 11/12 moderno via `DDraw.dll` e `D3DImm.dll`.
   - Permite forçar resolução interna 4K (3840×2160) com `Resolution = max` em `dgVoodoo.conf`.
   - Habilita filtragem anisotrópica de 16x (`Filtering = 16`) e anti-aliasing 8x MSAA (`Antialiasing = 8x`), eliminando cintilação de texturas (*pixel shimmering*) e suavizando polígonos.
   - [dgVoodoo2 no GitHub](https://github.com/dege-diosg/dgVoodoo2/releases) e [dgVoodoo2 General Readme](https://www.dege.freeweb.hu/dgVoodoo2/ReadmeGeneral/).

2. **Aspect Ratio Hor+ Widescreen (16:9)**:
   - O executável original calcula a projeção de câmera 4:3 com base no fator float `0.625` (`00 00 20 3F`) no offset `0xEB354` de `kain2.exe`.
   - A substituição desse valor por `0.46875` (`00 00 F0 3E`) implementa suporte nativo Hor+ para telas 16:9, ampliando o campo de visão horizontal (FOV) sem achatar ou esticar o modelo de Raziel e a geometria 3D.
   - Hash original de `kain2.exe`: `9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a`.
   - Hash verificado de `kain2.exe` com Hor+ 16:9: `396a757334daa8fdf8930de70a63929bbe0cb0d6bc3250ce5a2dd50056c1e243`.
   - [Guia Widescreen Hor+ no PCGamingWiki](https://www.pcgamingwiki.com/wiki/Legacy_of_Kain:_Soul_Reaver#Widescreen_resolution).

3. **Pós-processamento ReShade FX (`sr1-reshade-fx`)**:
   - Mod de ReShade no ModDB ([sr1-reshade-fx](https://www.moddb.com/mods/sr1-reshade-fx)).
   - Opera como injetor de pós-processamento sobre a camada Direct3D 11 fornecida pelo dgVoodoo2 (`dxgi.dll`), adicionando oclusão de ambiente (Ambient Occlusion), suavização subpixel SMAA, correção de cor/contraste cinematográfico e nitidez adaptativa (LumaSharpen/CAS).

4. **Pacote de Texturas Aprimoradas (`soul-reaver-1-texture-mini-mod`)**:
   - Mod de texturas no ModDB ([soul-reaver-1-texture-mini-mod](https://www.moddb.com/mods/soul-reaver-1-texture-mini-mod)).
   - Atualiza o arquivo `textures.big` original (168.693.760 bytes), substituindo texturas de baixa resolução do modelo de Raziel (faixas, rosto, garras e asas) por versões de alta definição sem alterar a malha poligonal.
   - Preserva o jogo original mantendo backup automático em `.soul-reaver-ptbr/textures.original.big`.

### Extração e identificação das falas

Usar The Sound of Her Wings e seu código disponível como referência de decodificação para voices.dat. A documentação registra cortes heurísticos, incluindo trechos unidos ou fragmentados; por isso cada WAV extraído precisa ser conciliado com as solicitações reais do jogo. Soul Spiral serve à investigação de recursos de bigfile.dat. Nenhuma dessas referências comprova um caminho de reinserção. [The Sound of Her Wings, atualizado em 18/02/2012](https://www.thelostworlds.net/Software/The_Sound_of_Her_Wings.html), [extração de áudio PC, atualizado em 18/02/2007](https://www.thelostworlds.net/HowTo/Extract_Soul_Reaver_Audio_PC.html).

Usar REA com um provedor nativo compatível, como Ghidra, para localizar no executável as rotinas de leitura, identificação e reprodução de fala. O projeto oferece inspeção de assembly, pseudocódigo e referências; sua documentação indica limitações específicas de provedores, inclusive suporte experimental de Ghidra no Windows. Não existe evidência de suporte pronto a Soul Reaver. Registrar versão do REA, provedor e evidências de cada conclusão. [REA, documentação consultada em 14/10/2026](https://github.com/morluto/rea).

O executável examinado contém 479 entradas com ID, offset e tamanho, cobrindo todo o `voices.dat`. O índice 291 foi confrontado com leituras e buffers reais do processo. A ferramenta `tools/inspect_voices.py` extrai pelos limites dessa tabela, protegida pelos hashes da base. O vínculo entre todos os índices, personagens e cenas ainda precisa de catálogo; a posição aproximada de um WAV não será usada como identidade final.

### Reprodução do mod

O piloto de 15/10/2026 comprovou reinserção em um intervalo de duração fixa de `voices.dat`. Para a primeira dublagem, seguir esse caminho: converter para PCM16 mono a 22.050 Hz, adaptar a fala à duração disponível e preencher a sobra com silêncio, mantendo todos os offsets. O instalador deverá gerar o candidato a partir da cópia do jogador e manter backup verificado. Uma camada x86 de áudios externos permanece alternativa caso os limites de duração impeçam a adaptação.

Na reinserção, o mecanismo original continua controlando volume, pausa, retomada, interrupção e conclusão. Esses comportamentos precisam de testes de cena; conservar o tamanho do arquivo não é prova suficiente. Entradas sem substituição permanecem originais e contam como falta de cobertura. Se a alternativa de hook for adotada, ela deverá também silenciar o canal original sem remover música/efeitos e preservar esses contratos.

A ferramenta local já gera um candidato para uma entrada e o jogo reproduziu a amostra. Isso não comprova os contratos de pausa, retomada, pulo, interrupção nem a cena natural. Esses testes e um piloto com outros personagens precedem a dublagem em lote. O hook usado para acionar a fila durante a investigação não é um runtime de mod distribuível.

### Vozes locais

Modelo do piloto: Qwen/Qwen3-TTS-12Hz-1.7B-Base, revisão `fd4b254389122332181a7c3db7f27e918eec64e3`, totalmente local. A amostra aprovada de Raziel usa uma referência do áudio original, conforme escolha posterior do usuário. VoiceDesign continua alternativa para personagens que precisem de outra identidade. O ambiente já validado é Python 3.13.15 do Studio com overlay de dependências, BF16 e SDPA; não recriar o Studio nem migrar o ambiente sem necessidade. [Qwen3-TTS, consultado em 15/10/2026](https://github.com/QwenLM/Qwen3-TTS).

Criar primeiro três perfis separados: Raziel, Kain e o Ancião. O timbre de Raziel já foi aprovado pelo usuário na amostra v2. Kain, Ancião e demais personagens ainda precisam de referências e aprovação próprias, inclusive vozes incidentais. Nunca atribuir automaticamente a referência de Raziel a todos os índices.

Cada identidade terá referência aprovada, transcrição da referência, instruções de interpretação, pronúncias, parâmetros e revisão. Fixar checkpoints e versões, guardar hashes e registrar seeds quando disponíveis; guardar também os WAVs finais, pois seed não garante reprodução idêntica entre ambientes.

Medição do piloto Raziel: 6,08 s de saída em aproximadamente 28,3 s, incluindo carregamento do modelo; pico de memória CUDA alocada de aproximadamente 4.304 MiB. O WAV aprovado tem SHA-256 `4684647add6a98c71755862ad8be69390a0e8f1f3896d9e6c26db00b2389f01d`. A conferência ASR reconheceu as duas orações, com variação em Dumá. Essa medição de uma fala não é um benchmark de produção contínua.

### Processamento paralelo e retomada

Manter um único modelo carregado na GPU, com prompt de referência calculado uma vez por personagem. A API Base aceita listas de textos e reutilização de `voice_clone_prompt`. Comparar lotes de 1, 2 e 4 falas na RTX 4060 Ti de 16 GB antes de escolher o tamanho padrão; registrar tempo de carregamento separado, tempo de geração, segundos de áudio produzidos, pico de VRAM e falhas. Mais processos na mesma GPU não implicam ganho proporcional.

Extração, conversão e conferência de duração podem usar workers limitados de CPU enquanto a GPU gera o próximo lote. ASR também disputa GPU: executá-lo em fase separada ou medir explicitamente a concorrência. Identificação, tradução e revisão podem avançar por cenas, mas somente texto aprovado com personagem conhecido entra na síntese de produção.

Gravar cada saída e seus metadados de forma atômica; retomar somente quando hashes de texto, perfil, referência, parâmetros, modelo e áudio coincidirem. Um lote com falha não deve invalidar áudios anteriores. Não cortar silenciosamente falas longas nem acelerar automaticamente para fazê-las caber. Alterar batch size pode alterar a realização aleatória; referências e arquivos aprovados permanecem imutáveis.

### Implementação iniciada em 15/10/2026

| Entrega | Arquivos/responsabilidade | Verificação exigida |
|---|---|---|
| Catálogo e extração | `tools/`, catálogo gerado em `staging/` | 479 WAVs com IDs estáveis, comprimentos exatos, origem preservada |
| Produção e benchmark | gerador local, perfis por personagem e checkpoints | lotes 1/2/4 na GPU real; retomada sem regenerar saídas válidas; falas longas recusadas |
| Pacote piloto | manifesto JSON e somente PCM PT-BR gerado | índice 291 reproduz o hash já validado; pacote sem DAT, executável ou referência original |
| Instalador local | `installer/`, Tauri/Rust + React/TS/Tailwind | validação de base/pacote, backup, aplicação e restauração numa cópia; conflitos recusados |
| Próximo marco de campanha | catálogo de personagens e cenas naturais | cumprir M2/M3 antes da síntese integral; gráficos 4K, legendas e FMVs continuam abertos |

O produtor Python e seus modelos ficam no ambiente de criação. O aplicativo do jogador aplica apenas PCM já produzido por um backend Rust; não exige Python, CUDA, Qwen ou Unsloth. A interface exibirá somente componentes implementados como disponíveis e não apresentará progresso ou conclusão fictícios.

Caso o piloto com Qwen falhe nos critérios de PT-BR, avaliar Chatterbox com seu recurso específico de português brasileiro, sem produzir todo o corpus em dois sistemas. Isso é uma contingência de benchmark. [Repositório oficial Chatterbox, consultado em 14/10/2026](https://github.com/resemble-ai/chatterbox).

### Uso do Unsloth já instalado

O Unsloth entra como ferramenta opcional para ajuste fino se o piloto apresentar problemas persistentes de identidade, pronúncia ou interpretação. Sua documentação contempla treinamento de TTS compatível com Transformers a partir de pares de áudio e texto. Isso não comprova que a instalação local já execute o checkpoint Qwen3-TTS escolhido. [Guia oficial de treinamento TTS, consultado em 14/10/2026](https://unsloth.ai/docs/basics/text-to-speech-tts-fine-tuning).

Antes de treinar: identificar ambiente e versões existentes sem reinstalar o Studio; testar a compatibilidade do modelo; preparar dados PT-BR revisados por personagem; separar cenas de treino e avaliação; medir VRAM. A adoção depende de ganho audível em falas de avaliação que não participaram do treino, comparado ao piloto sem treinamento. Uma LoRA única com vozes misturadas não será presumida suficiente para manter identidades.

O primeiro piloto continua usando referências fixas sem ajuste fino. Caso necessário, o treinamento será um experimento posterior ao M3, sem alterar a integração do jogo nem exigir Unsloth no computador de quem instalar o mod. Seu custo será incluído na reestimativa.

## Catálogo e fluxo de produção

Organização prevista do repositório separado da pasta Steam. Os diretórios de código e produção serão criados durante a implementação, além dos documentos iniciais:

```text
soul-reaver-ptbr-mod/
  installer/            # aplicativo Tauri: React/TypeScript/Tailwind e backend Rust
  docs/                 # decisões, reprodução de testes e compatibilidade
  manifests/            # hashes da base e versões de ferramentas
  catalog/dialogue.jsonl
  localization/         # tradução, glossário e revisão
  voices/               # perfis e referências autorais
  tools/                # extração, síntese, conferência e empacotamento
  runtime/              # integração x86 e legendas
  staging/              # candidatos locais, fora do pacote público
  evidence/             # logs, capturas e matriz de cobertura
  dist/                 # pacote reproduzível do mod
```

Backups e extrações dos originais ficam fora do pacote distribuível e do controle de versão público.

Cada registro do catálogo deve conter: ID estável; origem DAT/vídeo; chave original; personagem; cena; texto inglês conferido; tradução PT-BR; direção emocional; pronúncias; duração/janela disponível; caminho do WAV; versão da voz; estados de revisão; evidência de execução no jogo. Um fragmento extraído pode corresponder a várias falas e uma fala pode ocupar vários fragmentos.

Fluxo: inventário → extração → transcrição assistida local → conferência pelo áudio e cena → identificação de personagem → tradução e adaptação → revisão → síntese → conferência automática e auditiva → integração → teste real → pacote.

Manter glossário para nomes e conceitos da série, tom literário e relações entre personagens. Adaptar o texto à janela da cena antes de acelerar a voz. Não usar troca de pitch como único meio de diferenciar personagens. Gerar candidatos apenas para falas que precisem de correção e reutilizar resultados aprovados por hash de texto, perfil e parâmetros.

## Marcos e critérios de aceite

| Marco | Responsável técnico | Depende de | Entrega e validação |
|---|---|---|---|
| M0 — Base preservada | Ferramentas/instalação | Nada | Cópia isolada, hashes completos, saves e configurações protegidos; iniciar o original e registrar áudio, vídeo, entrada e uma sessão de referência |
| M1 — 4K | Renderização x86 | M0 | Superfície 3D 3840×2160 comprovada, câmera/HUD proporcionais; testar material/espectral, menus, água/transparências e entrada/saída de FMV; registrar limitações da tela usada |
| M2 — Viabilidade de áudio | Engenharia reversa/runtime | M0 | Mapear e substituir pelo menos 10 eventos reais, incluindo fala longa, curta, repetida e interrompida; manter música/efeitos e eventos de conclusão; testar reinício, load e skip |
| M3 — Piloto completo | Tradução/voz/runtime | M1 e M2 | Aproximadamente 30 falas entre três personagens, legendas e um trecho de FMV; cena real em 4K com captura, sem áudio inglês duplicado ou travamento |
| M4 — Corpus completo | Localização/áudio | M3 | Inventário conciliado com todos os eventos identificados; cada fala recebe personagem, tradução revisada e áudio ouvido integralmente; registrar separadamente sons não verbais e recursos sem uso |
| M5 — Campanha validada | QA/runtime | M4 | Jogar a campanha do início ao fim e rotas opcionais; testar saves em pontos-chave, diálogos repetíveis, FMVs, skip/pausa/load e sequência final; zero pendências de fala ausente no escopo |
| M6a — Interface do instalador | Frontend/Tauri | Contrato de componentes definido | Interface navegável de detecção, seleção, revisão e progresso; usar diretórios temporários para testes; não simular instalação bem-sucedida quando ainda não houver pacote real |
| M6b — Mod instalável | Rust/empacotamento/QA | M5 e M6a | Aplicativo Tauri, instalador Windows .exe, pacote versionado, hashes, documentação e teste numa cópia limpa; repetir instalação/atualização/remoção sem perda de saves |

O M1 pode avançar enquanto o M2 é investigado, mas a produção em massa depende dos dois e do piloto M3. Não há necessidade de delegar tarefas para seguir este plano.

### Aceite específico de áudio e legendas

- Todas as falas do catálogo de campanha têm tradução revisada e voz atribuída; não há entradas de personagem desconhecido na versão final.
- O conjunto de IDs catalogados é reconciliado com tabelas/scripts extraídos e logs da campanha. A simples contagem de WAVs não comprova cobertura total.
- Fazer escuta humana de 100% dos áudios finais; ASR local pode sinalizar omissões, palavras extras e trocas, mas não substitui revisão.
- Zero clipping digital nos arquivos finais; volume de fala comparado com cenas de referência, música e efeitos preservados.
- Na janela disponível, começo e fim da substituição seguem os eventos medidos do original. Usar desvio de até 100 ms como alvo inicial para os limites dos eventos, ajustando por cena com evidência; não prometer sincronização labial de fonemas.
- Legendas com acentuação correta e legibilidade verificadas em 1080p, 1440p e 4K, sem cortar texto nas áreas seguras.
- Medir pico de VRAM, tempo por minuto de áudio e taxa de rejeição no piloto. Estimar o lote completo a partir dessas medidas.

## Vídeos e cobertura de todos os diálogos

Inspecionar auditivamente os 11 vídeos, incluindo intro, visões chrono, verse e créditos, para descobrir quais contêm fala. A presença de áudio não implica que todos tenham diálogos. Comparar com voices.dat para evitar dublações duplicadas ou trechos omitidos.

Se a fala estiver misturada com música/efeitos numa única faixa, a substituição exigirá reconstrução da mixagem. Testar separação local de fontes e avaliar resíduos audíveis; isso pode exigir edição manual. Não existe faixa limpa de música/efeitos comprovada nesta inspeção.

Preferir preservar os frames do vídeo e substituir seu áudio por um caminho compatível comprovado. Validar se há ferramenta de autoria Bink apropriada e disponível ou se será necessária interceptação da reprodução com trilha externa sincronizada. Decodificar com FFmpeg não demonstra capacidade de recodificar Bink compatível com este player. Repetir testes de seek, skip, pausa, retorno ao jogo e término natural.

Upscale visual futuro deve manter 4:3, cadência e duração dos frames, sem inventar detalhes obrigatórios para a primeira versão. Se a trilha traduzida de um vídeo não funcionar, a versão ainda não cumpre o objetivo de todos os diálogos.

## Empacotamento e reversão

O produto de instalação será um aplicativo Tauri 2 com interface simples em React, TypeScript, Vite e Tailwind CSS. A documentação do Tauri recomenda Vite para interfaces React e descreve a geração de instaladores Windows; Tailwind oferece integração própria com Vite. Referências consultadas em 14/10/2026: [frontend Tauri](https://v2.tauri.app/start/frontend/), [instaladores Windows](https://v2.tauri.app/distribute/windows-installer/) e [Tailwind com Vite](https://tailwindcss.com/docs/installation/using-vite).

Distribuir o aplicativo inicialmente como instalador Windows .exe via NSIS. Ele instala o gerenciador do mod; o usuário então escolhe a instalação do jogo para aplicar os componentes. Manter os componentes do mod em pacote ZIP versionado: base de integração, perfil gráfico 4K e áudio/legendas PT-BR. Escolher 4K não deve obrigar uma troca de idioma. O aplicativo Windows poderá ser x64, enquanto DLLs carregadas dentro de kain2.exe precisam ser x86.

Fluxo inicial da interface:

1. Localizar o jogo nas bibliotecas Steam, com seleção manual de pasta como alternativa.
2. Validar edição, hashes conhecidos, conflitos, jogo em execução e espaço disponível.
3. Selecionar gráficos 4K, dublagem PT-BR e legendas, respeitando dependências entre componentes.
4. Revisar alterações e tamanho dos downloads; iniciar instalação com progresso real por etapa.
5. Mostrar resultado e oferecer abrir o jogo, verificar integridade do mod, reparar, atualizar ou remover.

O backend Rust será responsável por leitura e escrita, validação de caminhos, downloads, hashes, backups, registro das alterações e restauração. A interface recebe estado tipado e eventos de progresso; não executa comandos de shell arbitrários nem recebe acesso irrestrito ao disco. Operações devem ficar restritas à pasta validada do jogo e aos diretórios de cache, configuração e backup do aplicativo. Validar caminhos finais e rejeitar travessia de diretórios e redirecionamentos inesperados ao extrair pacotes.

Usar staging e registro transacional para verificar o pacote antes da aplicação e recuperar interrupções. Evitar pedir privilégios administrativos por padrão; se a pasta escolhida não permitir escrita, explicar o bloqueio sem deixar instalação parcial. Distinguir atualizar o aplicativo Tauri de atualizar os componentes do mod; versões, compatibilidade e mecanismos de verificação terão contratos separados. Não incluir geração de voz, Unsloth ou pesos de IA no instalador dos jogadores.

Manter o repositório privado inicialmente. Releases privadas servirão ao desenvolvimento; não embutir tokens pessoais no aplicativo para baixar assets privados. Antes de distribuir a terceiros, definir um canal de artefatos acessível aos destinatários e a autenticidade dos manifestos/pacotes, além de avaliar assinatura do executável. A criação do repositório não equivale à publicação de uma versão jogável.

O instalador deverá detectar a pasta e a base por hashes; exibir incompatibilidades e impedir aplicação cega em versões desconhecidas. Detectar DLLs de outros mods e não sobrescrevê-las silenciosamente. Se alguma alteração de arquivo for indispensável, criar backup verificado e registrar antes/depois no manifesto de instalação.

O desinstalador removerá apenas arquivos rastreados do mod e restaurará backups somente quando o estado for o esperado. Arquivos alterados posteriormente e saves devem ser preservados. Validar também instalação interrompida e espaço insuficiente, com recuperação sem deixar a base parcialmente modificada.

Distribuir apenas código, configurações e assets próprios necessários. Não incluir executável, DATs originais ou cópias integrais dos vídeos do jogo. Quando necessário, aplicar transformações à cópia que o jogador já possui. Antes de publicação, registrar os termos aplicáveis a ferramentas, checkpoints, referências vocais e conteúdo gerado; não presumir que a licença do código cobre todos os assets. A documentação do dgVoodoo permite componentes individuais inalterados em mods, observadas suas condições; preservar os avisos correspondentes. A publicação pública é uma etapa posterior à criação e validação local do pacote.

## Riscos, limites e estimativa

| Risco | Tratamento |
|---|---|
| Catálogo de eventos e sincronia incompletos | Limites de 479 entradas conhecidos e índice 291 reproduzido; validar cenas naturais, interrupções e outros personagens antes do lote |
| Widescreen expõe recortes ou efeitos incorretos | Comparar cenas com a referência 4:3 e corrigir projeção/HUD; manter perfil de compatibilidade e registrar se 16:9 continuar pendente |
| Mudança de FPS altera o jogo | Separar esse experimento da entrega inicial 4K |
| Voz muda entre falas ou soa em português europeu | Referência fixa por personagem, avaliação PT-BR e regeneração direcionada |
| Tradução ultrapassa duração da cena | Adaptar redação e interpretação; evitar aceleração excessiva ou esticar cenas sem prova |
| FMV tem voz misturada e player restrito | Provar mixagem e integração de uma cena no piloto; reservar trabalho específico para essa parte |
| Biblioteca Python/CUDA incompatível no Windows | Ambiente isolado, dependências fixadas e teste de síntese local; avaliar WSL2 somente se necessário, sem alterar o ambiente global |
| Alegar cobertura completa cedo demais | Matriz de eventos, recursos e cenas; campanha integral e revisão de falas opcionais |

Estimativa atual de trabalho dedicado: 1–2 dias para automatizar reinserção e testar cenas, 4–8 horas de geração para os 57,456 minutos conhecidos (estimativa anterior ao benchmark contínuo), 3–7 dias de adaptação/revisão/sincronia e 2–4 dias para o instalador. Uma primeira dublagem para testes foi estimada em aproximadamente uma semana; o conjunto com 4K, legendas, vídeos e campanha em 2–4 semanas. As etapas se sobrepõem parcialmente; não são prazos garantidos. A estimativa inicial de 3–7 semanas tinha a reinserção ainda desconhecida. Reestimar após os lotes medidos e M3; a contagem de entradas DAT não mede os diálogos dos vídeos nem o esforço de revisão.

Primeira ação de implementação: M0 e, em seguida, uma prova restrita de 4K e substituição de fala. A primeira entrega jogável deve demonstrar Raziel, Kain e o Ancião em cena, com identidades vocais distintas, legendas e sincronização, antes de expandir para toda a campanha.

## O que permanece sem comprovação nesta etapa

Síntese local, extração pelos limites da tabela e reprodução de uma fala reinserida foram demonstradas. Permanecem pendentes a cena natural e sua sincronia, demais eventos/personagens, renderização 4K, legendas, integração Bink e o instalador. As 479 entradas de `voices.dat` não representam uma contagem revisada de todos os diálogos da campanha, pois incluem vocalizações e não cobrem automaticamente as falas em vídeos. O elenco completo e a cobertura de cenas ainda serão levantados.
