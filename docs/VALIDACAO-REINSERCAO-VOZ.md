# Validação da reinserção de voz

Investigação local em 15/10/2026, para decidir como instalar a dublagem na edição Steam clássica examinada.

## Estado atual e limites

O piloto descrito abaixo é o registro histórico da primeira reinserção. Desde então, o candidato local passou a conter 230 substituições reais em `voices.dat`, 159 traduções de menus/dicas, oito vídeos de história em português e legendas para os diálogos incluídos. A campanha completa ainda não está traduzida nem dublada.

- **Acionamento natural:** abertura inteira e primeiras instruções no jogo. A gravação da abertura corresponde às 16 janelas de voz PT-BR, com correlações de 0,969 a 0,987. O teste mais recente observou naturalmente os índices 151, 154, 183, 205, 230, 316, 374 e 476, com buffers capturados iguais aos novos intervalos e 22 trechos de legenda correspondentes ao texto corrigido. Foi executado com 167 entradas; os oito payloads observados foram preservados byte por byte no pacote instalado de 230 entradas. Evidências: `staging/localization-v1/complete-playback-verification.json` e `staging/localization-v4/tutorial-probe/verification.json`.
- **Reprodução instrumentada:** seis visões (`chrono3/5/7/9/11/13.bik`) e `verse.bik`, redirecionando a abertura para cada candidato. Todos os quadros foram decodificados pelo motor original; as oito janelas de fala passaram pela conferência do áudio WASAPI, com correlações de 0,968 a 0,999. Isso não comprova seus acionamentos naturais nas cenas da campanha. Evidências: `staging/fmv-dub-v2/playback/verification.json` e `verse-playback-v2/verification.json` (esta última substitui a prova da cartela antiga).
- **Texto visível:** menus PT-BR, legendas do tutorial e legendas dos vídeos foram capturados no jogo. A nova cartela `verse.bik` substitui o poema inglês e “To Be Continued” por português; a captura `staging/fmv-dub-v2/verse-playback-v2/end-card.png` mostra “Continua...”.
- **Instalação real:** a interface Tauri e seu IPC aplicaram e restauraram as vozes e 11 arquivos de localização em uma cópia isolada. O teste preservou o save e uma DLL gráfica de outro mod. Em seguida, aplicaram o pacote `local-review-v6` na Steam, conferindo todos os hashes e o save inalterado. Evidência: `staging/localization-v6/installer-ui-proof.json`.
- **Atualização de 191 para 224:** 33 entradas adicionadas, 190 payloads anteriores preservados e a variante 129 corrigida de Kain para Ariel, conforme o contexto do roteiro cortado. As variantes 126/135 com atribuição antiga foram rejeitadas na seleção. Os cinco primeiros ajustes de ritmo não constituem aprovação de escuta. A conferência adicional de ASR usou apenas um glossário de nomes, com resultados anteriores preservados; a equivalência ortográfica Kain/Cain ficou registrada separadamente. Evidências: `staging/localization-v5/package-delta.json`, `staging/cast-audit-v1/corrections.json` e `staging/campaign-context-v1/takes/all-checks.json`.
- **Atualização de 224 para 230:** adicionados os takes 116, 163, 173, 206, 225 e 307, aprovados pelo usuário após ouvir original e IA. Os 224 payloads anteriores, os oito vídeos e os outros assets foram preservados; apenas as vozes e o TSV de legendas receberam conteúdo adicional. O teste de instalação/restauração pela interface passou no fixture; a aplicação na Steam conferiu todos os hashes, o save e todos os demais arquivos na raiz, incluindo os de outros mods. Evidências: `staging/localization-v6/package-delta.json` e `installer-ui-proof.json`. A aprovação de escuta não comprova acionamento natural ou sincronia das seis cenas.
- **Repetição interrompida:** a execução com 224 entradas foi encerrada a pedido do usuário para abrir a comparação de dicção, evitando misturar os áudios. Não é uma nova prova completa da abertura. Registro: `staging/localization-v5/tutorial-probe/interrupted.json`. A prova anterior dos oito payloads permanece aplicável somente aos áudios preservados.
- **Integridade:** 16 testes do núcleo Rust passaram na validação atual (`staging/localization-v3/core-tests.log`). O build do frontend e do aplicativo nativo também passou. Esses resultados não substituem as provas de execução acima.
- **Escuta:** o usuário aprovou as amostras dos perfis de Kain, Ancião, Moebius, Melchiah, Zephon e Rahab; Raziel já havia sido aceito. `content/voice-review.json` registra o alcance da aprovação. Após ouvir a sequência original/IA, o usuário respondeu “está ótimo” e aprovou os takes exatos 116, 163, 173, 206, 225 (Guardião) e 307 (Ariel). Os hashes dos WAVs e das comparações constam em `content/dialogue-review.json`; os resultados anteriores de ASR foram preservados. Falas futuras, mixagem e sincronia no jogo não recebem aprovação automática. A amostra de Dumah continua sem avaliação explícita.
- **Idioma e sotaque:** português brasileiro sempre, com preferência por sotaque paulista e/ou mineiro quando possível, em traços leves e naturais. A direção está em `content/localization-policy.json` e `AGENTS.md`. O modelo atual recebe `Portuguese`, sem seletor regional; o sotaque exige escuta e não foi comprovado apenas por configuração ou ASR. Não houve regeneração das falas já aprovadas para impor essa preferência.

SHA-256 do `voices.dat` atualmente instalado: `92e9a4fd2b262cdd8922b1f96cd3e098c730169add761bf0cc4e6844baacdb88`. O save permanece `79f653cfd5e5d680896040532c7c11caf497c20cb5c0eb4f1b0346f83812a1f1`. Executável e arquivos gráficos não foram alterados pela localização.

O proxy de legendas `DINPUT.dll` encaminha DirectInput à DLL do Windows e só instala seu hook após validar o executável e o ponto de entrada. O journal dos assets exige backup externo, recusa arquivos de outros mods e não restaura sobre modificações posteriores sem verificação de propriedade. Vozes e assets têm journals separados; falhas intermediárias são reportadas como instalação parcial.

Permanecem pendentes: avisos de NPCs, falas com dicção sinalizada, variantes e material cortado ainda sem substituição, identificação de vozes restantes, acionamentos naturais além do tutorial, sincronia das cenas restantes e comportamento de pausa/skip/load ao longo da campanha. O piloto 291 ainda não foi acionado naturalmente na conversa com Dumah. Não há publicação autorizada nem validação de 4K nesta frente.

## Registro histórico do piloto 291

**Resultado: a substituição de uma fala em `voices.dat` foi reproduzida pelo próprio jogo.** O teste acionou o índice 291 pela fila interna de vozes, com instrumentação, durante a sequência de entrada/tela inicial. Ainda falta testar o acionamento natural e a sincronia na conversa com Dumah.

## Contrato encontrado

O executável contém uma tabela de 479 pares de inteiros de 32 bits: offset em bytes e tamanho em bytes. Na base inglesa examinada, a tabela está no endereço virtual `0x004FD810`, offset de arquivo `0x000FC210`. A rotina em `0x004D8600` enfileira o índice da voz; o item de debug `VOICE TEST` chama essa rotina.

Todas as 479 entradas têm tamanho positivo e alinhamento de 16 bits. Seus intervalos são consecutivos, sem sobreposição ou lacunas, cobrindo exatamente os 152.028.822 bytes de `voices.dat`: 57,456 minutos de PCM16 little endian, mono, 22.050 Hz. São entradas de áudio, não uma contagem revisada de diálogos: há vocalizações curtas e a identificação de personagens ainda precisa de catálogo. Falas em vídeos Bink são outro conjunto.

Isso resolve a principal incerteza do extrator por silêncio. A própria documentação de [The Sound of Her Wings](https://www.thelostworlds.net/Software/The_Sound_of_Her_Wings.html) descreve sua segmentação como heurística. Nesta investigação, os limites vieram do executável local e foram confrontados com leituras reais do processo.

O [KAIN2-PC](https://github.com/TheSerioliOfNosgoth/KAIN2-PC) também foi consultado. Seu código de voz examinado usa estruturas XA do PlayStation; ele não foi usado como prova do formato do executável Windows comercial. REA não foi necessário para este teste: a análise usou pefile/Capstone e a instrumentação usou Frida, em um diretório isolado.

## Amostra aplicada

| Item | Valor |
|---|---|
| Personagem | Raziel |
| Índice, começando em zero | 291 |
| Offset | 33.503.518 bytes |
| Tamanho reservado | 279.842 bytes, ou 6,345624 s |
| Texto PT-BR | Sua gratidão é prematura, Dumá. Eu não esqueci quem me lançou no abismo. |
| WAV de síntese | 24.000 Hz, mono, PCM16, 6,08 s |
| Conversão usada | PCM16 mono a 22.050 Hz, 268.128 bytes |
| Silêncio inicial/final | 8.954 / 2.760 bytes |

O áudio convertido e os silêncios ocupam exatamente o intervalo original. O DAT resultante mantém o tamanho e todos os bytes fora da entrada 291. Nenhum WAV com cabeçalho foi inserido diretamente no DAT e nenhuma fala posterior mudou de posição. O executável da cópia de teste permaneceu inalterado em disco.

```text
SHA-256 kain2.exe original:
9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a
SHA-256 voices.dat original:
e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5
SHA-256 voices.dat candidato:
135a2342e7b4fc50ba07158c22bf5856599848c120f0ca0663b6423c36d77439
```

## Evidência em execução

A execução usou exclusivamente `staging/integration-probe/game/kain2.exe`, numa cópia normal dos arquivos do jogo fora da Steam. Frida chamou a fila de vozes no thread de atualização do jogo depois da inicialização do áudio. Essa chamada foi uma ação de teste; não existe um hook de mod distribuível implementado.

O processo abriu o `voices.dat` candidato e leu o intervalo da entrada 291 em cinco blocos: quatro de 65.536 bytes e um de 17.698 bytes. A concatenação dos buffers capturados na criação dos recursos de áudio é idêntica, byte por byte, à entrada modificada inteira. O jogo também executou sua rotina de reprodução no canal 24 e alcançou a tela de título.

A saída Realtek do Windows foi gravada via WASAPI loopback, sem usar microfone. O trecho contém a frase PT-BR completa; Whisper small reconheceu as duas orações e transcreveu Dumá como “do má”. A gravação inclui outros sons da abertura: a correlação de forma de onda com a amostra isolada foi 0,299 e não é apresentada como prova de igualdade do áudio mixado. A igualdade exata foi medida nos buffers fornecidos pelo jogo.

Arquivos de evidência locais, ignorados pelo Git:

- `staging/integration-probe/patch-manifest.json`: hashes, intervalo e preenchimento.
- `staging/integration-probe/runtime-log.jsonl`: caminho aberto, fila, leituras e buffers.
- `staging/integration-probe/runtime-verification.json`: confronto dos buffers e dos originais.
- `staging/integration-probe/runtime-voice-291-loopback.wav`: trecho gravado da saída do Windows.
- `staging/integration-probe/runtime-voice-291-transcript.json`: conferência automática da gravação.
- `staging/integration-probe/runtime-screen-9.png`: tela de título alcançada.

Os hashes de `kain2.exe`, `voices.dat` e `savegame.her` da instalação original permaneceram iguais. A instrumentação bloqueou gravações de valores no Registro pelo processo de teste para preservar as preferências existentes. Os processos iniciados para o teste foram encerrados.

## Ferramenta de reprodução do patch

[`tools/inspect_voices.py`](../tools/inspect_voices.py) usa somente a biblioteca padrão do Python 3.9+. Ela valida os dois hashes de origem, confere a cobertura da tabela, extrai uma entrada para WAV ou gera um novo DAT. Recusa saída dentro da instalação de origem, arquivo de saída existente, executável desconhecido e voz maior que o intervalo disponível. Os três caminhos e essas quatro recusas foram exercitados localmente.

Exemplo PowerShell, na raiz do repositório, com Python no PATH e diretório `staging/integration-probe` existente:

```powershell
$jogo = 'D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver'
python tools/inspect_voices.py inspect --game $jogo
python tools/inspect_voices.py extract --game $jogo --id 291 --output staging/integration-probe/extraida-291.wav
python tools/inspect_voices.py patch --game $jogo --id 291 --replacement staging/integration-probe/replacement-22050.wav --lead-samples 4477 --output staging/integration-probe/novo-voices.dat
```

Os comandos equivalentes foram executados com o Python 3.13 do ambiente local, saídas `tool-original-291.wav` e `tool-patched-voices.dat`. O último comando exige o WAV já convertido para PCM16 mono a 22.050 Hz. O DAT produzido pela ferramenta teve o mesmo hash do candidato reproduzido pelo jogo. Esta ferramenta não instala o mod nem modifica o executável.

## Decisão para o próximo piloto

Para a primeira dublagem, usar reinserção com duração fixa e preenchimento com silêncio. A instalação pode partir do DAT que o jogador possui e aplicar somente as substituições geradas. Isso dispensa um hook permanente de reprodução para esse caminho; o instalador Tauri ainda precisa implementar validação, backup, aplicação e restauração.

Cada fala deve caber no seu intervalo; se a adaptação não couber, revisar o texto/interpretação ou avaliar outra arquitetura. Alterar tamanhos e offsets no executável não foi testado. Preservar duração e mecanismo originais reduz alterações, mas não comprova automaticamente sincronia em todas as cenas.

Pendências antes de produzir toda a campanha: testar a cena natural do índice 291; provar pausa, retomada, interrupção, pulo de cena e transições; pilotar outros personagens e falas encadeadas; identificar todos os locutores e eventos; integrar e validar os vídeos Bink e legendas; testar instalação/desinstalação. Renderização 4K não foi validada nesta investigação.
