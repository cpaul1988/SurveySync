@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SurveySync v9.3.0 - Browser Fallback

set "PYLAUNCH="
if exist "runtime\python.exe" (
  set PYLAUNCH="%CD%\runtime\python.exe"
)
if not defined PYLAUNCH where py >nul 2>&1
if not defined PYLAUNCH if %errorlevel%==0 (
  py -3.13 -V >nul 2>&1 && set "PYLAUNCH=py -3.13"
  if not defined PYLAUNCH py -3.12 -V >nul 2>&1 && set "PYLAUNCH=py -3.12"
  if not defined PYLAUNCH py -3.11 -V >nul 2>&1 && set "PYLAUNCH=py -3.11"
)
if not defined PYLAUNCH (
  python -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYLAUNCH=python"
)
if not defined PYLAUNCH goto :python_error

%PYLAUNCH% bootstrap_windows.py --browser
if errorlevel 1 goto :error
exit /b 0

:python_error
echo.
echo SurveySync requires Python 3.11, 3.12, or 3.13.
echo Python 3.14 is not used for this release because of current
echo PaddlePaddle/native-extension compatibility issues.
echo.
pause
exit /b 1

:error
echo.
echo SurveySync could not start.
pause
exit /b 1
