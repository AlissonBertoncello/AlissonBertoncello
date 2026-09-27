@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Login no Mercado Livre

echo.
echo   ============================================
echo     LOGIN NO MERCADO LIVRE AFILIADOS (1 vez)
echo   ============================================
echo.
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo   Rode primeiro o BUSCAR_OFERTAS.bat ^(ele instala o que falta^).
  pause
  exit /b 1
)
uv run python -m ofertas ml-login
echo.
echo   Agora teste: de dois cliques no INICIAR_BOT.bat
echo.
pause
