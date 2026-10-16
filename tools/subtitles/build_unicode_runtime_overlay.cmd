@echo off
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
call "%VCVARS%" x86
if errorlevel 1 exit /b 1
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
if "%~1"=="" (
  set "OUT=%ROOT%\staging\unicode-runtime-v3"
) else (
  set "OUT=%ROOT%\%~1"
)
for %%I in ("%OUT%") do set "OUT=%%~fI"
powershell -NoProfile -Command "$p=[IO.Path]::GetFullPath('%OUT%');$r=[IO.Path]::GetFullPath('%ROOT%\staging')+[IO.Path]::DirectorySeparatorChar;if(!$p.StartsWith($r,[StringComparison]::OrdinalIgnoreCase)){exit 1}"
if errorlevel 1 (echo Output must be a new directory under staging.& exit /b 2)
if exist "%OUT%" (echo Refusing to overwrite existing output: "%OUT%".& exit /b 2)
mkdir "%OUT%"
if errorlevel 1 exit /b 1
pushd "%OUT%"
cl /nologo /W4 /WX /EHsc /LD /DUNICODE /D_UNICODE /std:c++17 /Founicode_runtime_overlay.obj "%ROOT%\tools\subtitles\unicode_runtime_overlay.cpp" /link /OUT:unicode_runtime_overlay.dll /IMPLIB:unicode_runtime_overlay.lib /EXPORT:InitializeOverlay=_InitializeOverlay@4 /EXPORT:RenderOverlay=_RenderOverlay@12 /EXPORT:InitializeTextOverlay=_InitializeTextOverlay@0 /EXPORT:SetCaptionUtf8=_SetCaptionUtf8@4 /EXPORT:InitializeUiOverlay=_InitializeUiOverlay@0 /EXPORT:BeginUiFrame=_BeginUiFrame@0 /EXPORT:AddUiTextUtf8=_AddUiTextUtf8@20 /EXPORT:CommitUiFrame=_CommitUiFrame@0 d3d11.lib dxgi.lib d3dcompiler.lib windowscodecs.lib ole32.lib gdi32.lib user32.lib normaliz.lib
if errorlevel 1 goto failed
cl /nologo /W4 /WX /EHsc /DUNICODE /D_UNICODE /std:c++17 /Founicode_overlay_host.obj "%ROOT%\tools\subtitles\unicode_overlay_host.cpp" /link /OUT:unicode_overlay_host.exe d3d11.lib dxgi.lib
if errorlevel 1 goto failed
unicode_overlay_host.exe --ui "%OUT%\unicode_runtime_overlay.dll" "%OUT%\ui-hud-offscreen.bmp"
if errorlevel 1 goto failed
set "PNG=%ROOT%\staging\unicode-runtime-v1\unicode-overlay-panel-4k.png"
if not exist "%PNG%" set "PNG=--skip-png"
unicode_overlay_host.exe --text "%OUT%\unicode_runtime_overlay.dll" "%PNG%" "%OUT%\unicode-dynamic-text-capture.bmp"
if errorlevel 1 goto failed
if exist "%PNG%" unicode_overlay_host.exe "%OUT%\unicode_runtime_overlay.dll" "%PNG%" "%OUT%\unicode-overlay-capture.bmp"
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 1
