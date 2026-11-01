@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0faultline.ps1" %*
exit /b %errorlevel%
