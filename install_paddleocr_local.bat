@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title SurveySync 9.3.0 — FieldBookSync - PaddleOCR CPU Installer

set "LOG=%~dp0PaddleOCR_Install.log"
>"%LOG%" echo SurveySync 9.3.0 — FieldBookSync - PaddleOCR CPU Installer
>>"%LOG%" echo Started %DATE% %TIME%
>>"%LOG%" echo Folder %CD%

echo.
echo ============================================================
echo   SurveySync 9.3.0 — FieldBookSync - PaddleOCR-VL CPU Setup
echo ============================================================
echo.
echo This installs a compatibility-first CPU Paddle environment.
echo It builds a NEW environment first, verifies it, then switches it
echo into place so a failed install cannot destroy a working setup.
echo.
echo Full install log:
echo   %LOG%
echo.
set /p CONFIRM="Continue with CPU installation? [Y/N]: "
if /I not "%CONFIRM%"=="Y" exit /b 0

call :find_python
if not defined PYLAUNCH goto :no_python

echo Compatible Python: %PYLAUNCH%
%PYLAUNCH% -c "import sys; print(sys.executable); print(sys.version)" >>"%LOG%" 2>&1

set "NEWENV=.paddleenv_cpu_new"
if exist "%NEWENV%" rmdir /s /q "%NEWENV%"

echo.
echo [1/5] Creating isolated environment...
%PYLAUNCH% -m venv "%NEWENV%" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

set "PYPATH=%CD%\%NEWENV%\Scripts\python.exe"

echo [2/5] Updating pip...
"%PYPATH%" -m pip install --disable-pip-version-check --upgrade pip >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [3/5] Installing PaddlePaddle 3.2.1 CPU runtime...
"%PYPATH%" -m pip install "paddlepaddle==3.2.1" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [4/5] Installing PaddleOCR document parser...
"%PYPATH%" -m pip install --upgrade "paddleocr[doc-parser]" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [5/5] Verifying PaddleOCR-VL...
"%PYPATH%" -c "import paddle; from paddleocr import PaddleOCRVL; print('PaddlePaddle',paddle.__version__); print('CUDA compiled',paddle.device.is_compiled_with_cuda()); print('PaddleOCR-VL READY')" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

call :activate_new_env
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo   SUCCESS - PaddleOCR-VL CPU runtime is ready.
echo ============================================================
echo.
echo Open SurveySync ^> FieldBookSync ^> AI & OCR ^> Check installation.
echo For automatic safe CPU/GPU selection, run:
echo   install_paddleocr_auto.bat
echo.
echo Log: %LOG%
pause
exit /b 0

:find_python
set "PYLAUNCH="
if exist "runtime\python.exe" (
  "runtime\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYLAUNCH="%CD%\runtime\python.exe""
)
if defined PYLAUNCH exit /b 0
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -V >nul 2>&1 && set "PYLAUNCH=py -3.13"
  if not defined PYLAUNCH py -3.12 -V >nul 2>&1 && set "PYLAUNCH=py -3.12"
  if not defined PYLAUNCH py -3.11 -V >nul 2>&1 && set "PYLAUNCH=py -3.11"
)
if not defined PYLAUNCH (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if (3,11) ^<= sys.version_info[:2] ^<= (3,13) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYLAUNCH=python"
  )
)
exit /b 0

:activate_new_env
set "STAMP=%RANDOM%_%RANDOM%"
if exist ".paddleenv" (
  echo Backing up existing .paddleenv...
  if exist ".paddleenv_backup_%STAMP%" rmdir /s /q ".paddleenv_backup_%STAMP%"
  move ".paddleenv" ".paddleenv_backup_%STAMP%" >>"%LOG%" 2>&1
  if errorlevel 1 exit /b 1
)
move "%NEWENV%" ".paddleenv" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:no_python
echo.
echo ERROR: No compatible 64-bit Python 3.11, 3.12, or 3.13 was found.
echo Python 3.14 is not used for this Paddle environment.
echo Install Python 3.13 x64 and run this BAT again.
>>"%LOG%" echo ERROR: No compatible Python 3.11-3.13 found.
goto :hold

:failed
echo.
echo ERROR: PaddleOCR installation did not complete.
echo The exact error is preserved in:
echo   %LOG%
echo.
echo The prior .paddleenv was NOT replaced.
>>"%LOG%" echo FAILED %DATE% %TIME%
:hold
echo.
echo This window will remain open so the error is not hidden.
pause
exit /b 1
