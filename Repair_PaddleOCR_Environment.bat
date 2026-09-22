@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FieldBook Sync - Repair PaddleOCR Environment

echo.
echo ============================================================
echo   FieldBook Sync - Repair PaddleOCR Environment
echo ============================================================
echo.
echo This repair ONLY rebuilds the isolated .paddleenv folder.
echo It does NOT delete or reinstall:
echo   - FieldBook Sync projects or settings
echo   - the main .venv unless FieldBook Sync itself needs migration
echo   - Ollama or Qwen models
echo   - ArcGIS Pro / ArcMap
echo.
echo Existing Paddle model caches stored outside .paddleenv are left alone.
echo.

set "PYLAUNCH="
where py >nul 2>&1
if %errorlevel%==0 (
  py -3.13 -V >nul 2>&1 && set "PYLAUNCH=py -3.13"
  if not defined PYLAUNCH py -3.12 -V >nul 2>&1 && set "PYLAUNCH=py -3.12"
  if not defined PYLAUNCH py -3.11 -V >nul 2>&1 && set "PYLAUNCH=py -3.11"
)
if not defined PYLAUNCH (
  python -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYLAUNCH=python"
)
if not defined PYLAUNCH goto :python_error

for /f "tokens=2 delims=." %%A in ('%PYLAUNCH% -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))"') do set "_dummy=%%A"
%PYLAUNCH% -c "import sys; print('Using Python %d.%d.%d' % sys.version_info[:3])"

echo.
set /p CONFIRM="Rebuild only PaddleOCR now? [Y/N]: "
if /I not "%CONFIRM%"=="Y" exit /b 0

if exist ".paddleenv" (
  for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
  echo.
  echo Preserving existing Paddle environment as .paddleenv_backup_%STAMP% ...
  move ".paddleenv" ".paddleenv_backup_%STAMP%" >nul
  if errorlevel 1 goto :error
)

echo.
echo [1/4] Creating clean PaddleOCR environment...
%PYLAUNCH% -m venv .paddleenv
if errorlevel 1 goto :error

call .paddleenv\Scripts\activate.bat
set PYTHONHOME=
set PYTHONPATH=

echo.
echo [2/4] Updating pip...
python -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :error

echo.
echo [3/4] Installing PaddlePaddle CPU runtime...
python -m pip install "paddlepaddle==3.2.1" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
if errorlevel 1 goto :error

echo.
echo [4/4] Installing PaddleOCR document parser...
python -m pip install --upgrade "paddleocr[doc-parser]"
if errorlevel 1 goto :error

echo.
echo Verifying clean environment...
python -c "import sys, paddle; from paddleocr import PaddleOCRVL; print('Python', sys.version); print('PaddlePaddle', paddle.__version__); print('PaddleOCR-VL ready')"
if errorlevel 1 goto :error

echo.
echo ============================================================
echo   PaddleOCR repair completed successfully.
echo ============================================================
echo.
echo Start FieldBook Sync and click Check installation again.
echo.
pause
exit /b 0

:python_error
echo.
echo No compatible Python installation was found.
echo Install Python 3.13 x64 ^(recommended^) or Python 3.12/3.11,
echo then run this repair again. Python 3.14 is not used for the
 echo current PaddlePaddle Windows runtime.
echo.
pause
exit /b 1

:error
echo.
echo PaddleOCR repair did not complete.
echo The previous environment was preserved in a backup folder if it existed.
echo Review the error above or send the FieldBook Sync diagnostic log.
echo.
pause
exit /b 1
