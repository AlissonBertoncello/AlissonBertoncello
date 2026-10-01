@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Desativar inicio automatico

echo.
echo   ============================================
echo     DESATIVAR INICIO AUTOMATICO DO BOT
echo   ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\inicio_automatico.ps1" -Desativar
if errorlevel 1 (
  echo.
  echo   Algo deu errado. Tire um print desta janela e envie para analise.
)
echo.
pause
