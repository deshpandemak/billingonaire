@echo off
rem Start both the Billingonaire backend and UI dev server for local development.
rem
rem Backend launches in a new window on :8000 (TESTING=true, no Firebase creds needed).
rem Frontend Vite dev server launches in a new window on :5000.
rem Close either window to stop that server.
rem
rem Environment variables (all optional, set before calling this script):
rem   PYTHON_BIN   — Python interpreter (default: auto-detected from .venv)
rem   BACKEND_PORT — backend port (default: 8000)
rem   TESTING      — set to "false" to use real Firebase credentials
rem   RELOAD       — set to "false" to disable uvicorn --reload

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BACKEND_DIR=%SCRIPT_DIR%\billingonaire_backend"
set "UI_DIR=%SCRIPT_DIR%\billingonaire-ui"
set "REPO_ROOT=%SCRIPT_DIR%\.."

rem Locate Python.
if not defined PYTHON_BIN (
    if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
        set "PYTHON_BIN=%REPO_ROOT%\.venv\Scripts\python.exe"
    ) else if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
        set "PYTHON_BIN=%BACKEND_DIR%\venv\Scripts\python.exe"
    ) else (
        set "PYTHON_BIN=python"
    )
)

if not defined TESTING set TESTING=true
if not defined HOST set HOST=0.0.0.0
if not defined BACKEND_PORT set BACKEND_PORT=8000
if not defined RELOAD set RELOAD=true

echo ============================================
echo  Billingonaire -- local dev
echo ============================================
echo  Backend : http://localhost:%BACKEND_PORT%
echo  Frontend: http://localhost:5000
echo  TESTING : %TESTING%
echo ============================================
echo.

rem Launch backend in a new console window.
echo [backend] launching in new window...
start "Billingonaire Backend" cmd /c "set TESTING=%TESTING%&& set HOST=%HOST%&& set PORT=%BACKEND_PORT%&& set RELOAD=%RELOAD%&& \"%PYTHON_BIN%\" \"%BACKEND_DIR%\dev_server.py\""

rem Give uvicorn a moment to bind.
timeout /t 3 /nobreak >nul

rem Launch UI in a new console window.
echo [ui] launching in new window...
start "Billingonaire UI" cmd /c "cd /d \"%UI_DIR%\" && npm run dev"

echo.
echo Both servers are starting in separate windows.
echo Close those windows (or press Ctrl-C in each) to stop the servers.
echo.
pause
