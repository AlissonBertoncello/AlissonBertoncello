@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Painel de configuracao
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"

echo.
echo   ============================================
echo     PAINEL DE CONFIGURACAO DO BOT
echo   ============================================
echo   O painel abre no navegador. Feche esta janela para fechar o painel.
echo.
uv sync >nul
uv run python -m ofertas painel
if errorlevel 1 pause
