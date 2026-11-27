@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Busca crua no ML
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"

echo.
echo   ============================================
echo     BUSCA CRUA NO MERCADO LIVRE
echo   ============================================
echo   Busca produtos no ML por todos os caminhos, sem filtro.
echo   NAO envia nada para os grupos. Leva 1 a 3 minutos.
echo   FECHE O BOT ANTES: o teste usa o mesmo Chrome do bot.
echo.
uv run python -m ofertas buscar-ml
echo.
pause
