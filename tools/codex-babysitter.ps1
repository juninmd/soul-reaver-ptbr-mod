#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Reanima uma sessão do Codex quando o limite de uso (quota) é atingido.

.DESCRIPTION
    Vigia uma sessão interativa do Codex (`codex --yolo`) em outra janela. Enquanto
    ela estiver viva, apenas espera — nunca interfere no trabalho do usuário. Quando
    a sessão morre (tipicamente por esgotamento de quota), retoma a thread em modo
    headless com `codex exec resume <ThreadId>` e:

      * se a saída indicar limite de uso, calcula a espera (horário de reset quando
        a mensagem traz "try again at HH:MM", senão um cooldown fixo) e tenta de novo;
      * se terminar normalmente, para.

    Modelo inspirado no padrão do babysitter do agy (401 → relança; 429 → espera até
    o reset). Não usa Task Scheduler. Roda em background a partir da sessão.

.PARAMETER ThreadId
    UUID da thread a retomar (ex.: 01a145bd-02e0-7ec3-9fcb-d082f728d1de).

.EXAMPLE
    pwsh -NoProfile -File tools/codex-babysitter.ps1 -ThreadId <uuid>
    pwsh -NoProfile -File tools/codex-babysitter.ps1 -ThreadId <uuid> -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ThreadId,
    [string]$ProjectDir = "D:\Solutions\pessoal\soul-reaver-ptbr-mod",
    [string]$Prompt = "Continue exatamente de onde você parou, sem pedir confirmação. Finalize a tarefa pendente e, ao terminar, resuma em poucas linhas o que mudou e o que falta.",
    [int]$MaxRounds = 100,
    [int]$PollSeconds = 60,
    [int]$LimitCooldownMinutes = 60,
    [string]$LogDir,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
if (-not $LogDir) { $LogDir = Join-Path $ProjectDir "staging\codex-babysitter" }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$logFile = Join-Path $LogDir "babysitter.log"

function Write-Log([string]$message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-InteractiveCodex {
    # Sessão interativa do usuário: `codex --yolo` (TUI). Ignora o nosso próprio exec.
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match '(?i)codex' -and
            $_.CommandLine -match '(?i)--yolo' -and
            $_.CommandLine -notmatch '(?i)codex-babysitter' -and
            $_.CommandLine -notmatch '(?i)exec\s+resume'
        }
}

function Get-ResetWaitSeconds([string]$text, [int]$defaultMinutes) {
    $default = [int]($defaultMinutes * 60)
    if ($text -match '(?i)(?:try again|resets?|reset|available again)\s+(?:at|after)\s+([0-9]{1,2}):([0-9]{2})\s*([APap][Mm])?') {
        $hour = [int]$Matches[1]; $minute = [int]$Matches[2]; $ampm = $Matches[3]
        $now = Get-Date
        if ($ampm) {
            if ($ampm.ToUpper() -eq 'PM' -and $hour -lt 12) { $hour += 12 }
            if ($ampm.ToUpper() -eq 'AM' -and $hour -eq 12) { $hour = 0 }
        }
        $target = Get-Date -Hour $hour -Minute $minute -Second 0
        if ($target -le $now) { $target = $target.AddDays(1) }
        return [int][math]::Max(60, ($target - $now).TotalSeconds + 300)
    }
    if ($text -match '(?i)in\s+([0-9]+)\s*(minute|min|hour|hr|h)') {
        $value = [int]$Matches[1]
        $unit = $Matches[2].ToLower()
        $seconds = if ($unit -like 'h*') { $value * 3600 } else { $value * 60 }
        return [int][math]::Max(60, $seconds + 300)
    }
    return $default
}

$limitPattern = '(?i)(usage limit|rate limit|quota|too many requests|429|resource[_ ]exhausted|limit reached|limit resets|\blimit\b[^\r\n]*\b(left|reached|resets|exceeded)\b|\d+\s*%\s*left|try again)'

Write-Log "babysitter iniciado | thread=$ThreadId | dir=$ProjectDir | MaxRounds=$MaxRounds"
Write-Log "Prompt: $Prompt"

for ($round = 1; $round -le $MaxRounds; $round++) {
    # 1. Espera a sessão interativa terminar (não interfere no trabalho em andamento).
    while (Get-InteractiveCodex) {
        Write-Log "[r$round] sessao interativa do Codex ativa; aguardando ${PollSeconds}s."
        Start-Sleep -Seconds $PollSeconds
    }
    Write-Log "[r$round] nenhuma sessao interativa ativa; retomando headless."

    if ($DryRun) {
        Write-Log "[dry] codex exec --dangerously-bypass-approvals-and-sandbox --json resume $ThreadId `"$Prompt`""
        break
    }

    $roundLog = Join-Path $LogDir ("round-{0}-{1}.log" -f $round, (Get-Date -Format "yyyyMMdd-HHmmss"))
    $codexArgs = @("exec", "--dangerously-bypass-approvals-and-sandbox", "--json", "--skip-git-repo-check",
              "resume", $ThreadId, $Prompt)
    $output = & codex @codexArgs 2>&1 | Tee-Object -FilePath $roundLog
    $exit = $LASTEXITCODE
    $text = ($output | Out-String)
    Write-Log "[r$round] exec terminou (exit=$exit). log=$roundLog"

    if ($text -match $limitPattern) {
        $wait = Get-ResetWaitSeconds $text $LimitCooldownMinutes
        Write-Log "[r$round] limite de uso detectado; aguardando $wait s ($([math]::Round($wait/60,1)) min) antes de retomar."
        Start-Sleep -Seconds $wait
        continue
    }

    Write-Log "[r$round] sem sinal de limite e execucao concluida; encerrando babysitter."
    break
}

Write-Log "babysitter encerrado."
