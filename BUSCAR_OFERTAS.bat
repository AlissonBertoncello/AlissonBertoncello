@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Buscar ofertas

echo.
echo   ============================================
echo     BUSCAR OFERTAS NO MERCADO LIVRE
echo   ============================================
echo.
REM 1) Garante que o uv esta instalado (ele baixa o Python sozinho)
set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo   Instalando o 'uv' ^(so na primeira vez^)...
  winget install --id astral-sh.uv -e --accept-package-agreements --accept-source-agreements
  where uv >nul 2>nul
  if errorlevel 1 powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  where uv >nul 2>nul
  if errorlevel 1 (
    echo.
    echo   Nao consegui instalar o uv. Feche esta janela e abra de novo.
    pause
    exit /b 1
  )
)

REM 2) Instala/atualiza as dependencias (rapido depois da primeira vez)
echo   Preparando o ambiente ^(pode demorar na primeira vez^)...
uv sync
if errorlevel 1 (
  echo.
  echo   Algo deu errado ao preparar o ambiente.
  echo   Se apareceu "Failed to spawn: python", veja "Problemas comuns" no README.
  pause
  exit /b 1
)

REM 3) Busca as ofertas e mostra na tela (nao envia nada)
echo.
uv run python -m ofertas check
echo.
uv run python -m ofertas diagnostico
echo.
uv run python -m ofertas testar --mensagem
echo.
pause
