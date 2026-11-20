@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Bot de Ofertas - Atualizar

echo.
echo   ============================================
echo     ATUALIZAR O BOT (baixa a versao nova do GitHub)
echo   ============================================
echo   Seu .env, config.yaml e a pasta data NAO sao mexidos.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$pasta=(Get-Location).Path;" ^
  "Write-Host ('  Pasta do bot: ' + $pasta);" ^
  "Write-Host '  1/4 Fechando o painel e o bot que estiverem abertos...';" ^
  "Get-CimInstance Win32_Process | Where-Object { ($_.Name -match '^(python|pythonw|uv)(\.exe)?$') -and ($_.CommandLine -match 'ofertas') } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} };" ^
  "Start-Sleep -Seconds 2;" ^
  "$tmp=Join-Path $env:TEMP 'bot_ofertas_atualizar'; if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }; New-Item -ItemType Directory $tmp | Out-Null;" ^
  "Write-Host '  2/4 Baixando a versao nova...';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "Invoke-WebRequest 'https://github.com/AlissonBertoncello/AlissonBertoncello/archive/refs/heads/main.zip' -OutFile (Join-Path $tmp 'bot.zip') -UseBasicParsing;" ^
  "Write-Host '  3/4 Copiando os arquivos novos para a pasta do bot...';" ^
  "Expand-Archive (Join-Path $tmp 'bot.zip') -DestinationPath (Join-Path $tmp 'x') -Force;" ^
  "$origem=(Get-ChildItem (Join-Path $tmp 'x') -Directory | Select-Object -First 1).FullName;" ^
  "robocopy $origem $pasta /E /IS /IT /R:2 /W:2 /XF .env config.yaml /XD data .venv /NFL /NDL /NJH /NJS /NP | Out-Null;" ^
  "if ($LASTEXITCODE -ge 8) { throw 'nao consegui copiar alguns arquivos (feche as janelas do bot e tente de novo)' };" ^
  "Write-Host '  4/4 Conferindo...';" ^
  "if (Select-String -Path (Join-Path $pasta 'ofertas\painel.html') -Pattern 'ChatGPT' -Quiet) { Write-Host ''; Write-Host '  OK! Atualizado. Agora abra o CONFIGURAR.bat (o painel ja vem com o ChatGPT).' -ForegroundColor Green } else { throw 'os arquivos nao foram trocados' }"
if errorlevel 1 (
  echo.
  echo   Deu erro na atualizacao ^(mensagem acima^). Tire um print desta janela e mande.
)
echo.
pause
