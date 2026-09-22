@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Normal source launches are intentionally re-launched hidden so users see
REM only the native SurveySync WebView window. Use --console for diagnostics.
if /I "%~1"=="--console" (
  shift
  goto :run_visible
)
if /I not "%~1"=="--hidden" (
  if exist "%SystemRoot%\System32\wscript.exe" if exist "%~dp0launch_hidden.vbs" (
    "%SystemRoot%\System32\wscript.exe" "%~dp0launch_hidden.vbs" "%~f0" %*
    exit /b 0
  )
)
if /I "%~1"=="--hidden" shift

:run_visible
title SurveySync v9.3.0

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

%PYLAUNCH% bootstrap_windows.py %*
if errorlevel 1 goto :error
exit /b 0

:python_error
echo.
echo ============================================================
echo   Compatible Python required
echo ============================================================
echo.
echo SurveySync currently uses Python 3.11, 3.12, or 3.13.
echo Python 3.14 is intentionally not used because the current
echo PaddlePaddle Windows runtime is not reliably compatible with it.
echo.
echo Install Python 3.13 x64 side-by-side, then run this file again.
echo Your projects, profiles, Qwen models, and settings are unaffected.
echo.
pause
exit /b 1

:error
echo.
echo SurveySync could not start. A bootstrap diagnostic was written to:
echo %%LOCALAPPDATA%%\SurveySync\logs\bootstrap.log
echo.
echo For a visible troubleshooting console, run:
echo   run_windows.bat --console
echo.
pause
exit /b 1
