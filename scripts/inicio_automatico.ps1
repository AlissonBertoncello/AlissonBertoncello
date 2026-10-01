# Cria/remove a tarefa agendada do Windows que abre o INICIAR_BOT.bat:
#   - ao entrar no Windows (logon)
#   - sempre que o Windows registra uma rede conectada
#     (Microsoft-Windows-NetworkProfile/Operational, evento 10000)
# Uso: inicio_automatico.ps1 -Ativar | -Desativar
param([switch]$Ativar, [switch]$Desativar)

$ErrorActionPreference = "Stop"
$Nome = "Bot de Ofertas - inicio automatico"
$Pasta = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $Pasta "INICIAR_BOT.bat"

if ($Desativar) {
    if (Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
        Write-Host "  OK: inicio automatico DESATIVADO."
    } else {
        Write-Host "  O inicio automatico ja estava desativado."
    }
    exit 0
}

if (-not $Ativar) { Write-Host "Use -Ativar ou -Desativar"; exit 1 }
if (-not (Test-Path $Bat)) { Write-Host "  ERRO: nao achei $Bat"; exit 1 }

$Usuario = "$env:USERDOMAIN\$env:USERNAME"

# Gatilho 1: ao entrar no Windows (com 30 s de folga para a rede e o Docker)
$AoEntrar = New-ScheduledTaskTrigger -AtLogOn -User $Usuario
$AoEntrar.Delay = "PT30S"

# Gatilho 2: ao conectar numa rede (Wi-Fi ou cabo), inclusive ao voltar da suspensao
$Classe = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$AoConectar = New-CimInstance -CimClass $Classe -ClientOnly
$AoConectar.Enabled = $true
$AoConectar.Delay = "PT20S"
$AoConectar.Subscription = @"
<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[EventID=10000]]</Select></Query></QueryList>
"@

$Acao = New-ScheduledTaskAction -Execute "$env:ComSpec" -Argument "/c `"$Bat`"" -WorkingDirectory $Pasta

# IgnoreNew: se o bot ja foi aberto pela tarefa e continua rodando, nao abre outro.
# Sem limite de tempo e rodando tambem na bateria (notebook).
$Config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -StartWhenAvailable

# Roda como o seu usuario, na sua sessao (a janela do bot aparece na tela)
$Quem = New-ScheduledTaskPrincipal -UserId $Usuario -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Nome -Trigger @($AoEntrar, $AoConectar) -Action $Acao `
    -Settings $Config -Principal $Quem -Description "Abre o INICIAR_BOT.bat ao entrar no Windows e ao conectar na internet." `
    -Force | Out-Null

Write-Host "  OK: inicio automatico ATIVADO."
Write-Host "  O bot vai abrir sozinho ao entrar no Windows e sempre que a internet conectar."
Write-Host "  Tarefa: '$Nome' (Agendador de Tarefas do Windows)."
