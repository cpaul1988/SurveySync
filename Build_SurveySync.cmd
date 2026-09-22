@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build_SurveySync.ps1" %*
exit /b %ERRORLEVEL%
