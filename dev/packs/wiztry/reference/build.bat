@echo off
setlocal

:: Choose Python: WIZTRY_PY env var first, then .venv
if defined WIZTRY_PY (
    set "PYTHON=%WIZTRY_PY%"
) else (
    set "PYTHON=.venv\Scripts\python.exe"
)

:: Build
"%PYTHON%" -m PyInstaller --onefile --windowed --name WizTry --noconfirm --clean --distpath dist --workpath build --specpath build WizTry.py
if errorlevel 1 goto :fail

:: Verify the exe exists
if not exist dist\WizTry.exe goto :fail

exit /b 0

:fail
exit /b 1
