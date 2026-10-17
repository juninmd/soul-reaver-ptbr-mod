# Overlay HD para fundos dos menus

`tools/graphics/menu_background_overlay.cpp` é uma DLL x86 independente que
recebe dois PNGs opacos 4:3 e desenha um deles em uma RTV D3D11 escolhida pelo
caller. O módulo não localiza telas, instala hooks ou decide quando a tela
visível corresponde ao menu: a integração deve chamar `RenderMenuBackground`
somente quando o desenho nativo do fundo tiver sido identificado e suprimido.

## ABI

```cpp
HRESULT __stdcall InitializeMenuBackgrounds(
    const wchar_t* titlePng, const wchar_t* selectionPng);
HRESULT __stdcall RenderMenuBackground(
    ID3D11Device*, ID3D11DeviceContext*, ID3D11RenderTargetView*, UINT which);
void __stdcall ReleaseMenuBackgrounds();
```

`which` vale 0 para `titlePng` e 1 para `selectionPng`. A DLL usa WIC para
decodificar em RGBA8 no tamanho de origem; recusa arquivos acima de 64 MiB,
dimensões acima de 8192, mais de 256 MiB decodificados, razão diferente de
4:3 ou pixels com alpha diferente de 255. Só aceita contexto imediato, device
igual no contexto e na RTV, e RTV `R8G8B8A8_UNORM` sem MSAA. O fundo cabe
centralizado na RTV com viewport 4:3; as barras laterais ou superior/inferior
ficam sem escrita pelo overlay.

Os recursos D3D são criados sob demanda e armazenados para um device por vez.
`ReleaseMenuBackgrounds` libera as referências e a imagem decodificada. Cada
render exige D3D11.1 (`ID3D11Device1` e `ID3D11DeviceContext1`) e cria um estado
de contexto via `CreateDeviceContextState`. Se essa API não estiver disponível,
retorna erro antes de desenhar. O estado completo anterior é restaurado por
RAII ao sair da chamada.

## Build e prova offline

Em Windows com Visual Studio 18 Build Tools:

```cmd
tools\graphics\build_menu_background_overlay.cmd
```

O script compila x86 com `/W4 /WX`, produz DLL e host em
`staging/menu-background-overlay-v1/` e executa o host em WARP com as artes
versionadas em `content/art/`. O host lê a saída, verifica pixels alterados,
as barras do alvo 16:9, alguns estados D3D antes/depois, os dois fundos em
1280×960 e 3840×2160 e liberação/reinicialização. BMPs e log ficam em
`validate/105-menus-hd/overlay/`.

Essa prova valida o renderer isolado e o ABI. Não valida a identificação do
fundo no jogo, a ordem dos hooks, compatibilidade com o device do jogo, nem
ocultação de textos/seleções; esses pontos dependem de integração e de uma
rodada posterior autorizada no jogo.
