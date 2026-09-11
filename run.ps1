<#
.SYNOPSIS
fut-bin - Melhores Momentos (Pelada) para Windows (PowerShell)

.DESCRIPTION
Cria/ativa o ambiente virtual (.venv) e roda os scripts do pipeline.

.EXAMPLE
.\run.ps1 site
.\run.ps1 site --port 8000
.\run.ps1 folha_placar --source_video_path pelada.mp4 --fim 58:23 --intervalo 10
.\run.ps1 detectar_gols --source_video_path pelada.mp4 --cortar --output_dir gols
.\run.ps1 montar_video --partida partida.json --clipes gols/clipes
.\run.ps1 marcador
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$Command = "",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvDir = Join-Path $ScriptDir ".venv"

# 1. Detectar Python
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
}

if (-not $pythonCmd) {
    Write-Host "[ERRO] Python não foi encontrado no PATH." -ForegroundColor Red
    Write-Host "   Instale o Python em https://www.python.org/downloads/ e marque a opção 'Add python.exe to PATH'."
    Write-Host "   Ou instale pelo terminal: winget install Python.Python.3.12"
    exit 1
}

# 2. Criar / verificar ambiente virtual
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
$venvPip = Join-Path $VenvDir "Scripts\pip.exe"
$venvActivate = Join-Path $VenvDir "Scripts\Activate.ps1"

if (-not (Test-Path $venvActivate)) {
    Write-Host "🔧 Criando ambiente virtual em .venv ..." -ForegroundColor Cyan
    & $pythonCmd -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERRO] Falha ao criar ambiente virtual." -ForegroundColor Red
        exit 1
    }
    Write-Host "📦 Instalando dependências de requirements.txt ..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip -q
    & $venvPip install -r (Join-Path $ScriptDir "requirements.txt") -q
}

# Ativar variáveis de ambiente do venv no processo atual
$env:VIRTUAL_ENV = $VenvDir
$env:PATH = "$(Join-Path $VenvDir 'Scripts');$env:PATH"

# 3. Verificar ffmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "⚠ ffmpeg não encontrado no PATH." -ForegroundColor Yellow
    Write-Host "   Instale antes de continuar (ex.: winget install Gyan.FFmpeg ou baixe em https://ffmpeg.org)" -ForegroundColor Yellow
    Write-Host ""
}

function Show-Usage {
    Write-Host @"
Uso: .\run.ps1 <comando> [opções do script]

Comandos (ver README.md para o fluxo completo):
  site               Assistente completo no navegador (passo a passo, sem rodar nada na mão)
  folha_placar       Corte manual - folhas de contato do placar / conversão de horários -> gols.json
  detectar_gols      Corte manual - corta os clipes de gol (ou detecção automática do placar)
  montar_video       Corte manual - monta o vídeo final a partir de partida.json
  diagnosticar       Conferência da região/estabilidade do placar
  marcador           Abre o marcador.html isolado (sem servidor) no navegador padrão
  shell              Só ativa o ambiente virtual num subshell (sem rodar nada)

Exemplos:
  .\run.ps1 site
  .\run.ps1 site --port 8000
  .\run.ps1 folha_placar --source_video_path pelada.mp4 --fim 58:23 --intervalo 10
  .\run.ps1 detectar_gols --source_video_path pelada.mp4 --cortar --output_dir gols
  .\run.ps1 montar_video --partida partida.json --clipes gols/clipes
  .\run.ps1 marcador
"@
}

# Se chamado sem argumentos, exibir menu interativo
if ([string]::IsNullOrWhiteSpace($Command)) {
    Write-Host "==============================================================================" -ForegroundColor Green
    Write-Host "fut-bin - Melhores Momentos (Pelada)" -ForegroundColor Green
    Write-Host "=============================================================================="
    Write-Host ""
    Write-Host "Escolha um comando para executar:"
    Write-Host "  [1] site          - Assistente no navegador (recomendado)"
    Write-Host "  [2] marcador      - Abrir marcador.html no navegador"
    Write-Host "  [3] shell         - Abrir terminal com ambiente virtual ativado"
    Write-Host "  [4] folha_placar  - Corte manual (folhas de contato)"
    Write-Host "  [5] detectar_gols - Detecção de gols / corte"
    Write-Host "  [6] montar_video  - Montagem do vídeo final"
    Write-Host "  [7] diagnosticar  - Diagnóstico da região do placar"
    Write-Host "  [8] ajuda         - Exibir instruções de uso"
    Write-Host ""
    $escolha = Read-Host "Opção [1]"
    switch ($escolha) {
        "1" { $Command = "site" }
        "2" { $Command = "marcador" }
        "3" { $Command = "shell" }
        "4" { $Command = "folha_placar" }
        "5" { $Command = "detectar_gols" }
        "6" { $Command = "montar_video" }
        "7" { $Command = "diagnosticar" }
        "8" { $Command = "help" }
        ""  { $Command = "site" }
        default { $Command = $escolha }
    }
}

switch ($Command) {
    "site" {
        $hostVal = "127.0.0.1"
        $portVal = "8000"
        for ($i = 0; $i -lt $ScriptArgs.Length; $i++) {
            if ($ScriptArgs[$i] -eq "--host" -and $i + 1 -lt $ScriptArgs.Length) { $hostVal = $ScriptArgs[$i + 1] }
            if ($ScriptArgs[$i] -eq "--port" -and $i + 1 -lt $ScriptArgs.Length) { $portVal = $ScriptArgs[$i + 1] }
        }
        $url = "http://$hostVal`:$portVal"
        Start-Job -ScriptBlock { param($u) Start-Sleep -Milliseconds 1500; Start-Process $u } -ArgumentList $url | Out-Null
        & $venvPython (Join-Path $ScriptDir "assistente_web.py") @ScriptArgs
    }
    "folha_placar" {
        & $venvPython (Join-Path $ScriptDir "folha_placar.py") @ScriptArgs
    }
    "detectar_gols" {
        & $venvPython (Join-Path $ScriptDir "detectar_gols.py") @ScriptArgs
    }
    "montar_video" {
        & $venvPython (Join-Path $ScriptDir "montar_video.py") @ScriptArgs
    }
    "diagnosticar" {
        & $venvPython (Join-Path $ScriptDir "diagnosticar_placar.py") @ScriptArgs
    }
    "marcador" {
        Start-Process (Join-Path $ScriptDir "marcador.html")
    }
    "shell" {
        Write-Host "Ambiente virtual ativado (.venv)." -ForegroundColor Green
        powershell -NoExit
    }
    { $_ -in @("", "-h", "--help", "help", "/?") } {
        Show-Usage
    }
    default {
        Write-Host "❌ Comando desconhecido: $Command`n" -ForegroundColor Red
        Show-Usage
        exit 1
    }
}
