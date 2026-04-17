@echo off
REM =====================================================================
REM   Data Compliance Agent — Demo Launcher (Windows)
REM   Starts langgraph dev (backend) + pnpm dev (frontend) + opens browser
REM =====================================================================

setlocal EnableDelayedExpansion
set ROOT=%~dp0
cd /d "%ROOT%"

echo.
echo ========================================================
echo   Data Compliance Agent - Demo Launcher
echo ========================================================
echo.

REM --- Verify .env exists ---
if not exist ".env" (
  echo [ERROR] .env file missing at %ROOT%.env
  echo.
  echo Copy .env.example to .env and fill in GROQ_API_KEY:
  echo     copy .env.example .env
  echo     notepad .env
  echo.
  pause
  exit /b 1
)

REM --- Venv is optional; deps are installed globally on this machine ---
set VENV_ACTIVATE=
if exist ".venv\Scripts\activate.bat" (
  set VENV_ACTIVATE=.venv\Scripts\activate.bat ^&^&
  echo [info] Using virtual environment at .venv
) else (
  echo [info] No .venv found; running with system Python.
)

REM --- Verify frontend exists ---
if not exist "agent-chat-ui\package.json" (
  echo [WARN] agent-chat-ui frontend not found; skipping frontend launch.
  echo Backend will still start on port 2024.
  set SKIP_FRONTEND=1
)

echo [1/3] Starting LangGraph dev server on http://127.0.0.1:2024 ...
start "LangGraph Dev Server" cmd /k "%VENV_ACTIVATE% langgraph dev"

timeout /t 3 /nobreak > nul

if not defined SKIP_FRONTEND (
  echo [2/3] Starting Next.js frontend on http://localhost:3000 ...
  start "Next.js Frontend" cmd /k "cd agent-chat-ui && pnpm dev"

  timeout /t 4 /nobreak > nul

  echo [3/3] Opening browser ...
  start http://localhost:3000
) else (
  echo [2/3] Skipped frontend launch.
  echo [3/3] LangGraph Studio at http://127.0.0.1:2024
  start http://127.0.0.1:2024
)

echo.
echo ========================================================
echo   Demo running. Close the terminal windows to stop.
echo ========================================================
echo.
endlocal
