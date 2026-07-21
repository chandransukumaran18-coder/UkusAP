@echo off
title Derive Launcher

echo Starting Derive backend (FastAPI) on port 8000...
start /D "%~dp0Backend" "Derive Backend" cmd /k "python -m uvicorn main:app --reload --port 8000"

echo Starting Derive frontend (static server) on port 5500...
start /D "%~dp0Frontend" "Derive Frontend" cmd /k "python serve.py 5500"

echo Waiting for servers to start...
timeout /t 2 /nobreak >nul

echo Opening Derive in your browser...
start http://127.0.0.1:5500/derive-landing

echo.
echo Both servers are running in their own windows.
echo Close those windows (or press Ctrl+C inside them) to stop Derive.
pause
