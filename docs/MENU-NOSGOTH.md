# Fundo do menu principal — Nosgoth

O fundo candidato usa uma adaptação em 4:3 da arte do README, com Raziel à
esquerda e uma área escura à direita para as opções originais do jogo. Os botões,
a navegação, as fontes e o código do menu não são modificados por esta troca.
A arte-fonte está em `content/art/menu-nosgoth.png`.

## Integração nativa

No executável Steam Classic compatível, as referências em `0x4395CA` e `0x439E69`
carregam `\kain2\game\psx\frontend\title1.pti`. A imagem está na entrada 92 de
`bigfile.dat`, identificador `0xF2C63638`, offset `0xDD3000`, tamanho 491.540 bytes.
É uma TIM de 16 bits, com textura 512×480 e cabeçalho de 20 bytes.

O empacotador exige o SHA-256 conhecido do arquivo base, da imagem original e a
estrutura exata da entrada. Substitui somente os pixels; o cabeçalho TIM, a
tabela do arquivo, os offsets, o tamanho e os demais recursos permanecem iguais.
A conversão mantém a proporção da composição para apresentação em 4:3.
O resultado usa a resolução nativa dessa textura; não é uma textura HD em runtime.

## Gerar o pacote local

Com Python e Pillow disponíveis, na raiz do repositório:

```powershell
python tools/build_menu_background.py `
  --game "<copia-fonte-compativel>" `
  --image content/art/menu-nosgoth.png `
  --items-image content/art/menu-itens-nosgoth.png `
  --localization modules/localization/assets.json `
  --output staging/menu-nosgoth-v2
```

Escolha uma saída nova. O comando lê a origem e não executa o jogo. A opção
`--localization` preserva os payloads e manifestos existentes de menus e legendas;
sem ela, é criado um pacote contendo apenas o fundo.

A opção `--items-image` também troca os pixels de `bigback.pti`, fundo
compartilhado dos submenus: entrada 91, identificador `0xFAD128C0`, offset
`0xD5A800`, 491.540 bytes, TIM 512×480. É opcional; sem ela, esse recurso
permanece original. Os cabeçalhos das duas imagens e todos os demais bytes
do arquivo são preservados. A imagem principal aprovada mantém os mesmos pixels.

O resultado inclui `assets.json`, `asset-bigfile.dat`, a TIM, a arte-fonte,
prévias após conversão e um relatório de integridade. `asset-bigfile.dat` é uma
cópia local do arquivo de recursos com a textura substituída e contém dados do
jogo: permanece fora do Git e não constitui um pacote autorizado para distribuição.

## Aplicar e restaurar

O fundo pertence ao componente **Localização**, com os mesmos registros,
backups externos, travas e verificações de propriedade dos menus e legendas.
O componente aceita apenas a base `bigfile.dat` com SHA-256
`30295bb8bdd059a3001f4b30d68973fd2e6a3ae50ea444087c8a17e94adeb035`.

Para testes, use uma cópia isolada e a CLI recompilada com o suporte ao fundo:

```powershell
target/release/srmod.exe assets-apply "<copia-de-teste>" "staging/menu-nosgoth-v2/assets.json" "<backup-externo>"
target/release/srmod.exe assets-restore "<copia-de-teste>"
```

Quando o manifesto de `modules/localization/` inclui o fundo, o instalador o
aplica junto com **menus e legendas**. A restauração desse componente também
restaura o fundo original. Arquivos alterados posteriormente são recusados.

## Verificações e limites

```powershell
python -m unittest discover -s tools -p test_menu_background.py
cargo test --offline --locked -p soul-reaver-mod-core -p soul-reaver-mod-installer
```

Os materiais desta rodada ficam em `validate/101-menu-nosgoth/`. As prévias são
composições e decodificações offline, sem botões simulados sobrepostos. Conferir
a posição e a legibilidade dos textos, a seleção, os submenus e o retorno ao menu
exige uma rodada autorizada no jogo. O jogo não é aberto pelo empacotador ou pelos
testes unitários.

## Arte para seleção de itens e qualidade HD

A candidata `content/art/menu-itens-nosgoth.png` foi gerada com o imagegen
integrado em **1448×1086**, proporção 4:3. Segue a identidade do menu principal,
com pedra escura, bronze e luz espectral nas bordas. O centro fica livre para
o conteúdo interativo. Não contém textos, ícones de itens ou botões pintados.
O prompt completo está em `content/art/menu-itens-nosgoth.prompt.txt`.

O pacote `staging/menu-nosgoth-v2/` aplica essa arte ao recurso compartilhado
`bigback.pti`. O carregamento foi encontrado no executável em `0x47EE2E`.
A associação exata à tela de seleção pedida e o contraste com seus elementos
ficam para a avaliação no jogo: a troca também pode aparecer em outros submenus.
O módulo `modules/localization/` continua com a versão anterior, somente com
`title1.pti`; a candidata com os dois fundos está separada para validação.

A revisão em `validate/102-menu-itens-nosgoth/preview.html` permite alternar
entre a fonte e a conversão offline para 512×480 RGB555, apresentada em 4:3.
Essa comparação mostra a perda de resolução e cor da rota atual. A fonte
gerada foi preservada sem ampliação artificial; não corresponde a uma
renderização HD já integrada ao jogo.

Para aproveitar a fonte em resolução maior, é necessário acrescentar um
caminho de carregamento/renderização para esses fundos e conferir identificação
da imagem, proporção, recorte e composição com os textos e seleções nativos.
A ponte experimental em `tools/graphics/hd_texture_bridge.js` e seu cache
aceitam páginas 256×256 substituídas por 1024×1024 R16_UINT; não atendem
diretamente ao fundo TIM 512×480. Aumentar a resolução da janela ou fornecer
uma imagem maior ao empacotador atual continua produzindo a mesma textura
nativa reduzida. O suporte HD dos menus exige desenvolvimento e validação
específicos; ainda não está implementado.
