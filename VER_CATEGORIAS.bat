@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Categorias do Mercado Livre
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"

echo.
echo   ============================================
echo     CATEGORIAS DO MERCADO LIVRE
echo   ============================================
echo   Mostra os codigos (MLB...) para colar no config.yaml.
echo.
uv run python -m ofertas categorias

:pergunta
echo.
set "CAT="
set /p "CAT=  Digite um codigo para ver as subcategorias (ex.: MLB1276) ou ENTER para sair: "
if "%CAT%"=="" exit /b 0
uv run python -m ofertas categorias %CAT% --niveis 2
goto pergunta
