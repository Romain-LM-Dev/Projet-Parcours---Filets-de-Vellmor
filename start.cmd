@echo off
rem Lance start.ps1 sans toucher a la politique d'execution de PowerShell. Les options sont transmises.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
rem en cas d'erreur, la fenetre reste ouverte pour qu'on lise le message
if errorlevel 1 pause
