@echo off
:: This gets the directory where the batch file itself is located.
set "SCRIPTPATH=%~dp0"

:: This ensures the working directory is set correctly.
cd /d "%SCRIPTPATH%"

:: Execute the PowerShell script using its full, absolute path and exit.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPTPATH%SetCPUAffinity.ps1"
exit