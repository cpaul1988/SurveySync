@echo off
setlocal EnableExtensions
title FieldBook Sync - Install Local Vision Models

echo.
echo ============================================================
echo   SurveySync 9.3.0 — FieldBookSync - Local Vision Setup
echo ============================================================
echo.
where ollama >nul 2>&1
if errorlevel 1 goto :no_ollama

echo Ollama detected.
echo.
echo Recommended Balanced model:
echo   qwen3-vl:4b-instruct  ^(about 3.3 GB^)
echo   Best starting point for field-book handwriting + document vision.
echo.
set /p BAL="Install qwen3-vl:4b-instruct? [Y/N]: "
if /I "%BAL%"=="Y" (
  echo.
  ollama pull qwen3-vl:4b-instruct
  if errorlevel 1 goto :error
)

echo.
echo Optional Fast model for lower-memory PCs:
echo   qwen3-vl:2b-instruct  ^(about 1.9 GB^)
set /p FAST="Also install qwen3-vl:2b-instruct? [Y/N]: "
if /I "%FAST%"=="Y" (
  echo.
  ollama pull qwen3-vl:2b-instruct
  if errorlevel 1 goto :error
)

echo.
echo Optional Maximum Accuracy model:
echo   qwen3-vl:8b-instruct  ^(about 6.1 GB^)
set /p MAX="Also install qwen3-vl:8b-instruct? [Y/N]: "
if /I "%MAX%"=="Y" (
  echo.
  ollama pull qwen3-vl:8b-instruct
  if errorlevel 1 goto :error
)

echo.
echo Local vision setup finished.
echo Open FieldBook Sync ^> Analysis Engine and use Auto or Balanced.
echo NOTE: Qwen3-VL requires a current Ollama release.
echo.
pause
exit /b 0

:no_ollama
echo Ollama was not found on this computer.
echo.
echo Opening the official Ollama Windows download page...
start "" "https://ollama.com/download/windows"
echo.
echo Install Ollama, then run this file again.
pause
exit /b 1

:error
echo.
echo The model download did not complete. Update Ollama if Qwen3-VL is not recognized,
echo then run this file again.
pause
exit /b 1
