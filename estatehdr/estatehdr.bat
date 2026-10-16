@echo off
rem EstateHDR (Windows): estatehdr.bat process <folder> [opcje] | estatehdr.bat web | estatehdr.bat test
setlocal
set HERE=%~dp0
set VENV=%HERE%.venv
if not exist "%VENV%\Scripts\python.exe" (
  echo [EstateHDR] tworze srodowisko Pythona...
  python -m venv "%VENV%" || exit /b 1
  "%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
  "%VENV%\Scripts\python.exe" -m pip install -q -r "%HERE%requirements.txt" || exit /b 1
)
set PYTHONPATH=%HERE%;%PYTHONPATH%
if "%1"=="test" (
  cd /d "%HERE%" && "%VENV%\Scripts\python.exe" -m pytest -q tests
) else (
  "%VENV%\Scripts\python.exe" -m estatehdr %*
)
