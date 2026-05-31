@echo off
rem Start the Billingonaire backend in local dev mode (no Firebase credentials needed).
rem
rem Environment variables (all optional, set before calling this script):
rem   PYTHON_BIN  — path to Python interpreter (default: auto-detected from .venv)
rem   HOST        — bind address (default: 0.0.0.0)
rem   PORT        — bind port   (default: 8000)
rem   TESTING     — set to "false" if you have real Firebase credentials configured
rem   RELOAD      — set to "false" to disable uvicorn --reload

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
rem Strip trailing backslash from SCRIPT_DIR
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "REPO_ROOT=%SCRIPT_DIR%\..\.."

rem Locate Python: prefer repo-root .venv, then system python.
if not defined PYTHON_BIN (
    if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
        set "PYTHON_BIN=%REPO_ROOT%\.venv\Scripts\python.exe"
    ) else if exist "%SCRIPT_DIR%\venv\Scripts\python.exe" (
        set "PYTHON_BIN=%SCRIPT_DIR%\venv\Scripts\python.exe"
    ) else (
        set "PYTHON_BIN=python"
    )
)

if not defined TESTING set TESTING=true
if not defined HOST set HOST=0.0.0.0
if not defined PORT set PORT=8000
if not defined RELOAD set RELOAD=true

echo Starting Billingonaire backend (local dev)
echo   python : %PYTHON_BIN%
echo   address: %HOST%:%PORT%
echo   TESTING: %TESTING%
echo   reload : %RELOAD%
echo.

"%PYTHON_BIN%" "%SCRIPT_DIR%\dev_server.py"
