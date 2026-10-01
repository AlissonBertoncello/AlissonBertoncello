@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Ativar inicio automatico

echo.
echo   ============================================
echo     ATIVAR INICIO AUTOMATICO DO BOT
echo   ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\inicio_automatico.ps1" -Ativar
if errorlevel 1 (
  echo.
  echo   Algo deu errado. Tire um print desta janela e envie para analise.
)
echo.
echo   Lembrete: no Docker Desktop, marque "Start Docker Desktop when you sign in"
echo   ^(Settings ^> General^). Sem o Docker aberto, o WhatsApp nao funciona.
echo.
pause
