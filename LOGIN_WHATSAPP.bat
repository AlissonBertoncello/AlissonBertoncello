@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Conectar WhatsApp

echo.
echo   ============================================
echo     CONECTAR O WHATSAPP DO BOT (1 vez)
echo   ============================================
echo   Precisa do Docker Desktop instalado e ABERTO.
echo.
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo   Rode primeiro o BUSCAR_OFERTAS.bat ^(ele instala o que falta^).
  pause
  exit /b 1
)
uv run python -m ofertas whatsapp-login
echo.
echo   Copie os nomes dos grupos acima para "whatsapp:" no config.yaml,
echo   troque "destino: console" por "destino: whatsapp" e abra o INICIAR_BOT.bat
echo.
pause
