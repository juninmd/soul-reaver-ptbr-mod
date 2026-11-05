@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 exit /b %errorlevel%
if not exist staging\capture mkdir staging\capture
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /utf-8 tools\capture\dxgi_grab.cpp /Fostaging\capture\dxgi_grab.obj /Festaging\capture\dxgi_grab.exe /link d3d11.lib dxgi.lib user32.lib gdi32.lib
