@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title SurveySync 9.3.0 — FieldBookSync - PaddleOCR Auto Setup

set "LOG=%~dp0PaddleOCR_Auto_Install.log"
>"%LOG%" echo SurveySync 9.3.0 — FieldBookSync - PaddleOCR Auto Setup
>>"%LOG%" echo Started %DATE% %TIME%

call :find_probe_python
if not defined PROBEEXE (
  echo.
  echo A Python launcher was not found, so GPU compatibility cannot be safely probed.
  echo FieldBook Sync will use the compatibility-first CPU installer.
  >>"%LOG%" echo Probe Python unavailable; routing to CPU installer.
  call install_paddleocr_local.bat
  exit /b %ERRORLEVEL%
)

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

echo.
echo ============================================================
echo   SurveySync 9.3.0 — FieldBookSync - PaddleOCR Runtime Selection
echo ============================================================
echo.

if "!GPU_PRESENT!"=="1" (
  echo NVIDIA GPU: !GPU_NAME!
  echo VRAM:       !GPU_VRAM_MIB! MiB
  echo Compute:    !GPU_COMPUTE_CAP!
  echo Driver:     !GPU_DRIVER_VERSION!
  if defined GPU_CUDA_VERSION echo Driver CUDA: !GPU_CUDA_VERSION!
  echo.
) else (
  echo No NVIDIA GPU eligible for probing was detected.
  echo CPU PaddleOCR will be used.
  echo.
  >>"%LOG%" echo No NVIDIA GPU detected; routing to CPU.
  call install_paddleocr_local.bat
  exit /b !ERRORLEVEL!
)

if not "!GPU_SUPPORTED!"=="1" (
  echo GPU PaddleOCR is NOT being offered on this computer.
  echo.
  echo Reason:
  echo   !GPU_REASON!
  echo.
  echo FieldBook Sync will use CPU PaddleOCR instead. Qwen/Ollama can still
  echo use whatever NVIDIA GPU offload Ollama supports independently.
  echo.
  >>"%LOG%" echo GPU blocked: !GPU_REASON!
  call install_paddleocr_local.bat
  exit /b !ERRORLEVEL!
)

echo GPU PaddleOCR is compatible with the current official Windows wheel rules.
echo Selected PaddlePaddle: !GPU_PADDLE_VERSION!
echo Selected wheel channel: !GPU_CHANNEL!
echo.
echo   G = NVIDIA GPU PaddleOCR
 echo   C = Compatibility-first CPU PaddleOCR
choice /C GC /N /M "Choose Paddle runtime [G/C]: "
if errorlevel 2 (
  call install_paddleocr_local.bat
) else (
  call Install_PaddleOCR_GPU_Optional.bat
)
exit /b !ERRORLEVEL!

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
