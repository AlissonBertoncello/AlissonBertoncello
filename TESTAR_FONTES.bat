@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Teste das fontes
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"

echo.
echo   ============================================
echo     TESTE DAS FONTES DE OFERTAS
echo   ============================================
echo   Testa de onde o bot consegue trazer ofertas.
echo   NAO envia nada para os grupos. Leva 1 a 3 minutos.
echo   FECHE O BOT ANTES: o teste usa o mesmo Chrome do bot.
echo.
uv run python -m ofertas testar-fontes
echo.
pause
