@echo off
cd /d "%~dp0"
set PY=%WIZTRY_PY%
if not defined PY set PY=.venv\Scripts\python.exe
"%PY%" -m PyInstaller --onefile --windowed --name WizTry --noconfirm --clean --distpath dist --workpath build --specpath build WizTry.py
if errorlevel 1 exit /b 1
if not exist dist\WizTry.exe exit /b 1
