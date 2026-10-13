@echo off
rem Lance stop.ps1 sans toucher a la politique d'execution de PowerShell. Les options sont transmises.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
