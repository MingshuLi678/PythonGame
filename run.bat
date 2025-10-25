@echo off
REM One-step runner for cmd / double-click: create venv, install deps, run main.py
REM Run from project root.

SETLOCAL
SET ROOT=%~dp0
SET VENV=%ROOT%\.venv

IF NOT EXIST "%VENV%\Scripts\python.exe" (
    echo Creating virtual environment in %VENV%...
    python -m venv "%VENV%"
)

SET PY=%VENV%\Scripts\python.exe
IF NOT EXIST "%PY%" (
    echo Virtual environment python not found; falling back to system python
    SET PY=python
)

echo Upgrading pip, setuptools, wheel...
"%PY%" -m pip install --upgrade pip setuptools wheel

echo Installing requirements...
"%PY%" -m pip install -r "%ROOT%requirements.txt"

echo Launching game (main.py)...
"%PY%" "%ROOT%main.py"

echo Done.
ENDLOCAL

PAUSE
