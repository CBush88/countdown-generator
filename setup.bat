@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Countdown Generator - setup
echo ============================================
echo.

set "PYEXE="
for %%C in (py python python3) do (
    if not defined PYEXE (
        %%C --version >nul 2>&1 && set "PYEXE=%%C"
    )
)

if not defined PYEXE (
    echo Python was not found on this computer.
    echo.
    echo Opening the Python download page...
    echo.
    echo After installing Python:
    echo   1. Tick "Add python.exe to PATH" on the first screen.
    echo   2. Finish the install, then run setup.bat again.
    echo.
    start "" https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Using [!PYEXE!] - 
!PYEXE! --version
echo.

echo Installing dependencies...
!PYEXE! -m pip install --upgrade pip >nul 2>&1
!PYEXE! -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Setup complete. Starting Countdown Generator...
echo.
!PYEXE! "countdown-studio.py"
if errorlevel 1 pause
endlocal