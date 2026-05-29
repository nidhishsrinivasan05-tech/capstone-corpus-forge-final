@echo off
REM ============================================================
REM  Corpus Forge - launcher
REM  Starts the Flask web app using the project's virtualenv.
REM  Double-click this file, or run "run.bat" from a terminal.
REM ============================================================

setlocal

REM Always run from the folder this script lives in.
cd /d "%~dp0"

REM Prefer the project venv Python; fall back to system Python.
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [warn] .venv not found, falling back to system "python".
    set "PYTHON=python"
)

echo Starting Corpus Forge...
echo Open http://127.0.0.1:5000 in your browser. Press Ctrl+C to stop.
echo.

"%PYTHON%" run.py

REM Keep the window open if the server exits or errors out.
echo.
echo Server stopped.
pause
endlocal
