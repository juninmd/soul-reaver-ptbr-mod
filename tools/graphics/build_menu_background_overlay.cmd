@echo off
setlocal
set "ROOT=%~dp0..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" (echo VS Build Tools vcvarsall.bat not found.& exit /b 1)
call "%VCVARS%" x86
if errorlevel 1 exit /b 1
set "OUT=%ROOT%\staging\menu-background-overlay-v1"
if exist "%OUT%" (echo Refusing to overwrite existing output: "%OUT%".& exit /b 2)
mkdir "%OUT%"
if errorlevel 1 exit /b 1
pushd "%OUT%"
cl /nologo /W4 /WX /EHsc /LD /DUNICODE /D_UNICODE /std:c++17 /Fomenu_background_overlay.obj "%ROOT%\tools\graphics\menu_background_overlay.cpp" /link /MACHINE:X86 /OUT:menu_background_overlay.dll /IMPLIB:menu_background_overlay.lib /EXPORT:InitializeMenuBackgrounds=_InitializeMenuBackgrounds@8 /EXPORT:RenderMenuBackground=_RenderMenuBackground@16 /EXPORT:ReleaseMenuBackgrounds=_ReleaseMenuBackgrounds@0 d3d11.lib dxgi.lib d3dcompiler.lib windowscodecs.lib ole32.lib
if errorlevel 1 goto failed
cl /nologo /W4 /WX /EHsc /DUNICODE /D_UNICODE /std:c++17 /Fomenu_background_host.obj "%ROOT%\tools\graphics\menu_background_host.cpp" /link /MACHINE:X86 /OUT:menu_background_host.exe d3d11.lib dxgi.lib
if errorlevel 1 goto failed
set "CAPTURE=%ROOT%\validate\105-menus-hd\overlay"
if not exist "%CAPTURE%" mkdir "%CAPTURE%"
menu_background_host.exe "%OUT%\menu_background_overlay.dll" "%ROOT%\content\art\menu-nosgoth.png" "%ROOT%\content\art\menu-itens-nosgoth.png" "%CAPTURE%" > "%CAPTURE%\warp-run.log" 2>&1
if errorlevel 1 (type "%CAPTURE%\warp-run.log"& goto failed)
type "%CAPTURE%\warp-run.log"
popd
exit /b 0
:failed
popd
exit /b 1
