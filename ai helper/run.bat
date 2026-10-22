@echo off
setlocal enabledelayedexpansion
title Ghost Pilot - AI Autonomous Copilot

echo =====================================================================
echo  Ghost Pilot - 100%% Hands-Free Real-Time AI Copilot (Windows)
echo =====================================================================
echo.

cd /d "%~dp0"

:: 1. Detect Python executable
set "PYTHON_EXE="

where python >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=python"
    goto :PYTHON_FOUND
)

where py >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_EXE=py"
    goto :PYTHON_FOUND
)

:: Check common Windows Python install locations
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*" "%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON_EXE=%%D\python.exe"
        goto :PYTHON_FOUND
    )
)

echo [ERROR] Python was not found on your system!
echo Please download and install Python 3.10+ from https://www.python.org/
echo (Make sure to check "Add Python to PATH" during installation).
pause
exit /b 1

:PYTHON_FOUND
echo [*] Using Python: !PYTHON_EXE!

:: 2. Create virtual environment if it does not exist
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment in .venv ...
    !PYTHON_EXE! -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [*] Virtual environment created successfully.
)

:: 3. Create .env from template if missing
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Initializing .env from .env.example ...
        copy .env.example .env >nul
    )
)

:: 4. Install / Update dependencies
echo [*] Verifying dependencies from requirements.txt ...
.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies!
    pause
    exit /b 1
)

:: 5. Launch Application
echo [*] Launching Ghost Pilot Desktop Overlay...
echo [*] Window display affinity set: Hidden from screenshare and recording tools.
echo.
.\.venv\Scripts\python.exe main.py

if !errorlevel! neq 0 (
    echo.
    echo [NOTICE] Application closed with code !errorlevel!.
    pause
)
