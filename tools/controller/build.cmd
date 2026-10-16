@echo off
setlocal
set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if not exist "%VCVARS%" (echo Visual Studio Build Tools vcvarsall.bat not found.& exit /b 2)
call "%VCVARS%" x64
if errorlevel 1 exit /b 1
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
if "%~1"=="" (
  set "OUT=%ROOT%\staging\controller-v1"
) else (
  for %%I in ("%~1") do set "OUT=%%~fI"
)
if not exist "%OUT%" mkdir "%OUT%"
if errorlevel 1 exit /b 1
pushd "%OUT%"
cl /nologo /W4 /WX /O2 /MT /EHsc /Brepro /utf-8 /DUNICODE /D_UNICODE /D_WIN32_WINNT=0x0601 /std:c++17 "%ROOT%\tools\controller\bridge.cpp" /link /SUBSYSTEM:WINDOWS /ENTRY:wmainCRTStartup winmm.lib user32.lib gdi32.lib shell32.lib /OUT:sr-dualsense.exe
if errorlevel 1 goto failed
popd
exit /b 0
:failed
popd
exit /b 1
