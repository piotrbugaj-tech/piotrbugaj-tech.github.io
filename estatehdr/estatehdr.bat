@echo off
rem EstateHDR (Windows) - uruchamianie jedna komenda.
rem   estatehdr.bat process <folder> [opcje]   obrobka folderu (serie bracketingowe / pojedyncze zdjecia)
rem   estatehdr.bat web [--port 8765]           lokalny interfejs webowy (http://127.0.0.1:8765)
rem   estatehdr.bat test [opcje pytest]         testy automatyczne
rem   estatehdr.bat presets  /  group <folder>
rem Przy pierwszym uruchomieniu tworzy .venv i instaluje requirements.txt (ponownie tylko po jego zmianie).
setlocal EnableExtensions DisableDelayedExpansion
set "HERE=%~dp0"
set "VENV=%HERE%.venv"
if defined ESTATEHDR_VENV set "VENV=%ESTATEHDR_VENV%"
if not defined PYTHON set "PYTHON=python"
set "VPY=%VENV%\Scripts\python.exe"
if exist "%VPY%" goto :deps
echo [EstateHDR] tworze srodowisko Pythona w "%VENV%" ... 1>&2
%PYTHON% -m venv "%VENV%" || exit /b 1
"%VPY%" -m pip install -q --upgrade pip 1>&2 || exit /b 1
:deps
rem requirements.txt is installed when its SHA-1 differs from the stamp written after the last successful install
set "STAMP=%VENV%\.requirements.sha1"
set "SUM="
set "OLD="
"%VPY%" -c "import hashlib,sys;print(hashlib.sha1(open(sys.argv[1],'rb').read()).hexdigest())" "%HERE%requirements.txt" >"%STAMP%.new" || exit /b 1
set /p SUM=<"%STAMP%.new"
del "%STAMP%.new"
if not defined SUM exit /b 1
if exist "%STAMP%" set /p OLD=<"%STAMP%"
if "%OLD%"=="%SUM%" goto :run
echo [EstateHDR] instaluje zaleznosci (requirements.txt) ... 1>&2
"%VPY%" -m pip install -q -r "%HERE%requirements.txt" 1>&2 || exit /b 1
>"%STAMP%" echo %SUM%
:run
set "PP=%HERE%"
if defined PYTHONPATH set "PP=%HERE%;%PYTHONPATH%"
set "PYTHONPATH=%PP%"
set "SUBCMD=%~1"
if "%SUBCMD%"=="" goto :help
if /i "%SUBCMD%"=="help" goto :help
if "%SUBCMD%"=="-h" goto :help
if "%SUBCMD%"=="--help" goto :help
if /i "%SUBCMD%"=="test" goto :test
"%VPY%" -m estatehdr %*
exit /b %ERRORLEVEL%
:help
"%VPY%" -m estatehdr --help
exit /b %ERRORLEVEL%
:test
rem every argument after "test" goes to pytest (like "$@" in estatehdr.sh)
set "ARGS=%*"
set "ARGS=%ARGS:*test=%"
cd /d "%HERE%" && "%VPY%" -m pytest -q tests %ARGS%
exit /b %ERRORLEVEL%
