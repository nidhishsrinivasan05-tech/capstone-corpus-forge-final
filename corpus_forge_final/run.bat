@echo off
REM ============================================================
REM  Corpus Forge - launcher
REM  Starts the Flask web app using the project's virtualenv.
REM  Double-click this file, or run "run.bat" from a terminal.
REM
REM  NOTE: the actual project lives a couple of folders below
REM  this launcher, so we cd into it explicitly.
REM ============================================================

setlocal

REM Move into the real project folder (relative to this script).
cd /d "%~dp0corpus_forge_final 2\corpus_forge_final"

if not exist "run.py" (
    echo [error] Could not find run.py in:
    echo         %CD%
    echo Make sure this launcher sits next to the "corpus_forge_final 2" folder.
    pause
    exit /b 1
)

REM Prefer the project venv Python; fall back to system Python.
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [warn] .venv not found, falling back to system "python".
    set "PYTHON=python"
)

echo Starting Corpus Forge...
echo Project folder: %CD%
echo Open http://127.0.0.1:5000 in your browser. Press Ctrl+C to stop.
echo.

"%PYTHON%" run.py

REM Keep the window open if the server exits or errors out.
echo.
echo Server stopped.
pause
endlocal
