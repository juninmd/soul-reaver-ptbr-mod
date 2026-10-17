@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x86
if errorlevel 1 exit /b %errorlevel%
if not exist staging\subtitles-v1 mkdir staging\subtitles-v1
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /LD tools\subtitles\runtime.cpp /Fostaging\subtitles-v1\runtime.obj /link /DEF:tools\subtitles\runtime.def /OUT:staging\subtitles-v1\DINPUT.dll /MAP:staging\subtitles-v1\DINPUT.map /IMPLIB:staging\subtitles-v1\DINPUT.lib bcrypt.lib winmm.lib user32.lib gdi32.lib gdiplus.lib dinput8.lib dxguid.lib setupapi.lib hid.lib
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT tools\subtitles\test_host.cpp /Fostaging\subtitles-v1\test_host.obj /Festaging\subtitles-v1\test_host.exe
