@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title SurveySync 9.3.0 — FieldBookSync - Local AI Setup

echo.
echo ============================================================
echo   SurveySync 9.3.0 — FieldBookSync - Local AI Setup
echo ============================================================
echo.
echo This setup has two independent parts:
echo   1. Ollama local vision - Balanced qwen3-vl:4b-instruct recommended
echo      Optional qwen3-vl:2b-instruct Fast and qwen3-vl:8b-instruct Maximum Accuracy profiles
echo   2. PaddleOCR-VL 1.6 - document / PointID locator
echo.
echo Both run locally after their model/runtime files are installed.
echo.
set /p Q="Set up Ollama local vision models now? [Y/N]: "
if /I "%Q%"=="Y" (
  call install_qwen_local.bat
  if errorlevel 1 goto :child_failed
)

set /p P="Set up PaddleOCR-VL now? [Y/N]: "
if /I "%P%"=="Y" (
  call install_paddleocr_auto.bat
  if errorlevel 1 goto :child_failed
)

echo.
echo ============================================================
echo   Local AI setup launcher finished successfully.
echo ============================================================
echo.
pause
exit /b 0

:child_failed
echo.
echo ============================================================
echo   A local AI installer reported an error.
echo ============================================================
echo.
echo This launcher will NOT hide it behind a generic completion message.
echo For Paddle failures, check PaddleOCR_Auto_Install.log,
echo PaddleOCR_Install.log, or PaddleOCR_GPU_Install.log in this folder.
echo.
pause
exit /b 1
