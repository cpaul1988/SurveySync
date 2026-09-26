@echo off
setlocal
cd /d "%~dp0"
call Build_SurveySync.cmd %*
exit /b %ERRORLEVEL%
