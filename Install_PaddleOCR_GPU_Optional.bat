@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title SurveySync 9.3.0 — FieldBookSync - PaddleOCR NVIDIA GPU Installer

set "LOG=%~dp0PaddleOCR_GPU_Install.log"
>"%LOG%" echo SurveySync 9.3.0 — FieldBookSync - PaddleOCR NVIDIA GPU Installer
>>"%LOG%" echo Started %DATE% %TIME%

 echo.
echo ============================================================
echo   SurveySync 9.3.0 — FieldBookSync - OPTIONAL NVIDIA GPU OCR
 echo ============================================================
echo.
echo This uses the same PaddleOCR-VL 1.6 workflow on the GPU.
echo It does not lower image resolution or weaken PointID validation.
echo A new environment is verified before replacing the existing one.
echo.

call :find_probe_python
if not defined PROBEEXE goto :probe_failed

set "PROBEFILE=%TEMP%\fbs_paddle_gpu_probe_%RANDOM%_%RANDOM%.txt"
"%PROBEEXE%" %PROBEARG% "%CD%\probe_paddle_gpu.py" --env >"%PROBEFILE%" 2>>"%LOG%"
set "PROBERC=!ERRORLEVEL!"

set "GPU_PRESENT=0"
set "GPU_SUPPORTED=0"
set "GPU_NAME="
set "GPU_VRAM_MIB="
set "GPU_COMPUTE_CAP="
set "GPU_DRIVER_VERSION="
set "GPU_CUDA_VERSION="
set "GPU_CHANNEL="
set "GPU_PADDLE_VERSION="
set "GPU_REASON=GPU compatibility probe did not return a usable result."

if exist "%PROBEFILE%" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%PROBEFILE%") do set "GPU_%%A=%%B"
  type "%PROBEFILE%" >>"%LOG%"
  del /q "%PROBEFILE%" >nul 2>&1
)

if not "!GPU_PRESENT!"=="1" goto :no_gpu

 echo NVIDIA hardware/driver detected:
echo   GPU:        !GPU_NAME!
echo   VRAM:       !GPU_VRAM_MIB! MiB
echo   Compute:    !GPU_COMPUTE_CAP!
echo   Driver:     !GPU_DRIVER_VERSION!
echo   Driver CUDA: !GPU_CUDA_VERSION!
>>"%LOG%" echo GPU !GPU_NAME! / !GPU_VRAM_MIB! MiB / CC !GPU_COMPUTE_CAP! / driver !GPU_DRIVER_VERSION! / CUDA !GPU_CUDA_VERSION!

if not "!GPU_SUPPORTED!"=="1" goto :unsupported_gpu
if not defined GPU_CHANNEL goto :probe_failed
if not defined GPU_CUDA_VERSION goto :probe_failed
if not defined GPU_COMPUTE_CAP goto :probe_failed

echo.
echo Compatibility check: PASS
echo Selected PaddlePaddle: !GPU_PADDLE_VERSION!
echo Selected official wheel channel: !GPU_CHANNEL!
echo.
set /p CONFIRM="Install/replace PaddleOCR with the NVIDIA GPU runtime? [Y/N]: "
if /I not "!CONFIRM!"=="Y" exit /b 0

call :find_install_python
if not defined PYEXE goto :no_python

set "NEWENV=.paddleenv_gpu_new"
if exist "%NEWENV%" rmdir /s /q "%NEWENV%"

 echo.
echo [1/5] Creating isolated GPU environment...
"%PYEXE%" %PYARG% -m venv "%NEWENV%" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed
set "PYPATH=%CD%\%NEWENV%\Scripts\python.exe"

 echo [2/5] Updating pip...
"%PYPATH%" -m pip install --disable-pip-version-check --upgrade pip >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

 echo [3/5] Installing PaddlePaddle GPU !GPU_PADDLE_VERSION! (!GPU_CHANNEL!)...
"%PYPATH%" -m pip install "paddlepaddle-gpu==!GPU_PADDLE_VERSION!" -i "https://www.paddlepaddle.org.cn/packages/stable/!GPU_CHANNEL!/" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

 echo [4/5] Installing PaddleOCR document parser...
"%PYPATH%" -m pip install --upgrade "paddleocr[doc-parser]" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

 echo [5/5] Verifying real CUDA execution and PaddleOCR-VL import...
"%PYPATH%" -c "import paddle; from paddleocr import PaddleOCRVL; assert paddle.device.is_compiled_with_cuda(), 'Paddle is not CUDA-enabled'; assert paddle.device.cuda.device_count()>0, 'No CUDA device visible'; paddle.set_device('gpu:0'); x=paddle.to_tensor([1.0,2.0]); y=x*2; assert y.numpy().tolist()==[2.0,4.0]; print('PaddlePaddle',paddle.__version__); print('CUDA devices',paddle.device.cuda.device_count()); print('PaddleOCR-VL GPU READY')" >>"%LOG%" 2>&1
if errorlevel 1 goto :failed

call :activate_new_env
if errorlevel 1 goto :failed

 echo.
echo ============================================================
echo   SUCCESS - NVIDIA GPU OCR is installed and verified.
echo ============================================================
echo.
echo FieldBook Sync will now prefer GPU:0 automatically.
echo Open Analysis Engine ^> Check installation; it should report GPU.
echo.
echo Log: %LOG%
pause
exit /b 0

:find_probe_python
set "PROBEEXE="
set "PROBEARG="
if exist "runtime\python.exe" (
  set "PROBEEXE=%CD%\runtime\python.exe"
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  set "PROBEEXE=%CD%\.venv\Scripts\python.exe"
  exit /b 0
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -V >nul 2>&1
  if not errorlevel 1 (
    set "PROBEEXE=py"
    set "PROBEARG=-3"
    exit /b 0
  )
)
where python >nul 2>&1
if not errorlevel 1 set "PROBEEXE=python"
exit /b 0

:find_install_python
set "PYEXE="
set "PYARG="
if exist "runtime\python.exe" (
  set "PYEXE=%CD%\runtime\python.exe"
  exit /b 0
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -V >nul 2>&1 && set "PYEXE=py" && set "PYARG=-3.13"
  if not defined PYEXE py -3.12 -V >nul 2>&1 && set "PYEXE=py" && set "PYARG=-3.12"
  if not defined PYEXE py -3.11 -V >nul 2>&1 && set "PYEXE=py" && set "PYARG=-3.11"
)
if not defined PYEXE (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if (3,11) ^<= sys.version_info[:2] ^<= (3,13) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYEXE=python"
  )
)
exit /b 0

:activate_new_env
set "STAMP=%RANDOM%_%RANDOM%"
if exist ".paddleenv" (
  echo Backing up existing .paddleenv...
  move ".paddleenv" ".paddleenv_backup_%STAMP%" >>"%LOG%" 2>&1
  if errorlevel 1 exit /b 1
)
move "%NEWENV%" ".paddleenv" >>"%LOG%" 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:no_gpu
echo.
echo ERROR: NVIDIA GPU/driver detection failed.
echo Use install_paddleocr_auto.bat or install_paddleocr_local.bat for CPU OCR.
>>"%LOG%" echo ERROR: NVIDIA GPU not detected by compatibility probe.
goto :hold

:unsupported_gpu
echo.
echo ============================================================
echo   GPU PADDLE INSTALL BLOCKED - CPU OCR RECOMMENDED
 echo ============================================================
echo.
echo !GPU_REASON!
echo.
echo No GPU packages were installed and the existing .paddleenv was not touched.
echo Run install_paddleocr_auto.bat to be routed to the CPU installer.
>>"%LOG%" echo GPU BLOCKED: !GPU_REASON!
goto :hold

:probe_failed
echo.
echo ERROR: GPU compatibility could not be determined safely.
echo No GPU install will be attempted when compatibility values are missing.
echo Use install_paddleocr_local.bat for CPU OCR.
>>"%LOG%" echo ERROR: GPU compatibility probe unavailable/incomplete.
goto :hold

:no_python
echo ERROR: Python 3.11, 3.12, or 3.13 x64 is required.
>>"%LOG%" echo ERROR: Compatible Python not found.
goto :hold

:failed
echo.
echo ERROR: GPU PaddleOCR installation/verification failed.
echo The existing .paddleenv was NOT replaced.
echo See: %LOG%
>>"%LOG%" echo FAILED %DATE% %TIME%
:hold
echo.
pause
exit /b 1
