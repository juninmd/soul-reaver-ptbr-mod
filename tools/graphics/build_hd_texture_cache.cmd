@echo off
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
call "%VCVARS%" x86
if errorlevel 1 exit /b 1
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
set "OUT=%ROOT%\staging\texture-runtime-v1"
if not exist "%OUT%" mkdir "%OUT%"
pushd "%OUT%"
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /DUNICODE /D_UNICODE /LD "%ROOT%\tools\graphics\hd_texture_cache.cpp" /link /def:"%ROOT%\tools\graphics\hd_texture_cache.def" /out:hd_texture_cache.dll /implib:hd_texture_cache.lib d3d11.lib dxgi.lib bcrypt.lib
if errorlevel 1 goto failed
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /DUNICODE /D_UNICODE "%ROOT%\tools\graphics\hd_texture_cache_host.cpp" hd_texture_cache.lib /link /out:hd_texture_cache_host.exe d3d11.lib dxgi.lib bcrypt.lib
if errorlevel 1 goto failed
hd_texture_cache_host.exe "%OUT%\fixtures"
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 1
