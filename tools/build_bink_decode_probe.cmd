@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x86
if errorlevel 1 exit /b %errorlevel%
if not exist staging\fmv-hd-runtime-v1\codec-probe mkdir staging\fmv-hd-runtime-v1\codec-probe
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT tools\bink_decode_probe.cpp /Fostaging\fmv-hd-runtime-v1\codec-probe\probe.obj /Festaging\fmv-hd-runtime-v1\codec-probe\probe.exe
exit /b %errorlevel%
