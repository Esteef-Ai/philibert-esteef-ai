# Philibert Code by Esteef.Ai - start it from inside a Philibert install.
#
#   <Philibert>\code\start.ps1 [-Headless]
#
# Philibert Code lives in <Philibert>\code\ and borrows Philibert's Python, Ollama and model store,
# and its notes vault. Its own settings, chats, memory and logs go in <Philibert>\data\code\.
# If Philibert is already running, its Ollama is shared (one copy of a model in the graphics card);
# otherwise this starts the drive's Ollama and stops it again when Philibert Code closes.
param([switch]$Headless)
$ErrorActionPreference = "Stop"

$code = $PSScriptRoot
$root = Split-Path $code -Parent
$rt   = Join-Path $root "runtime\win-x64"
$py   = Join-Path $rt "python\python.exe"
$ol   = Join-Path $rt "ollama\ollama.exe"
$app  = Join-Path $code "app\NeuralDock_launcher.py"
$data = Join-Path $root "data\code"
$logs = Join-Path $data "logs"

function Say($msg) {
    if ($Headless) { Write-Host $msg; return }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($msg, "Philibert Code", "OK", "Warning") | Out-Null
}

# Philibert first: Philibert Code is an add-on to it, never on its own.
foreach ($need in @((Join-Path $root "app\NeuralDock_launcher.py"), $py, $ol)) {
    if (-not (Test-Path $need)) {
        Say "Philibert Code needs Philibert.`n`nIt was not found (or is not set up yet) in:`n$root`n`nInstall or start Philibert once first, then start Philibert Code again."
        exit 1
    }
}
if (-not (Test-Path $app)) { Say "Philibert Code's program is missing from $code\app. Run its Setup again."; exit 1 }
New-Item -ItemType Directory -Force $data, $logs | Out-Null

function Free-Port([int]$start, [int]$tries) {
    foreach ($p in $start..($start + $tries - 1)) {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
        try { $l.Start(); $l.Stop(); return $p } catch { }
    }
    throw "no free port from $start"
}

function Ollama-Up([int]$port) {
    try { Invoke-RestMethod "http://127.0.0.1:$port/api/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

# -- Ollama: Philibert's own, if it is running; else start the drive's -------------------------------
$started = $null
$port = $null
$mine = Get-Process ollama -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $ol }
foreach ($o in $mine) {
    $listen = Get-NetTCPConnection -State Listen -OwningProcess $o.Id -ErrorAction SilentlyContinue |
              Where-Object { $_.LocalAddress -in @("127.0.0.1", "::1", "0.0.0.0", "::") } | Select-Object -First 1
    if ($listen -and (Ollama-Up $listen.LocalPort)) { $port = $listen.LocalPort; break }
}
$env:OLLAMA_MODELS          = Join-Path $root "models"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
$env:OLLAMA_NOPRUNE         = "1"      # never delete model files on start
$env:OLLAMA_LOAD_TIMEOUT    = "30m"    # a USB hard drive can take minutes to load a big model
if ($port) {
    Write-Host "Sharing Philibert's Ollama on port $port"
} else {
    $port = Free-Port 11435 20
    $env:OLLAMA_HOST = "127.0.0.1:$port"
    $started = Start-Process -FilePath $ol -ArgumentList "serve" -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "ollama.log") -RedirectStandardError (Join-Path $logs "ollama.err.log")
    $up = $false
    foreach ($k in 1..60) {
        if ($started.HasExited) { break }
        if (Ollama-Up $port) { $up = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $up) { Say "Ollama, which runs the AI models, did not start. The details are in data\code\logs\ollama.err.log."; exit 1 }
    Write-Host "Started the drive's Ollama on port $port"
}

# -- Philibert Code ------------------------------------------------------------------------------------
Remove-Item Env:ND_PORTABLE -ErrorAction SilentlyContinue        # the full app, not Philibert's portable one
$env:PYTHONNOUSERSITE = "1"                                        # never this computer's own Python packages
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH       = Join-Path $code "pylib"                    # Philibert Code's extra packages
$env:PHILIBERT_ROOT   = $root
$env:ND_DATA_DIR      = $data
$env:ND_OLLAMA_URL    = "http://127.0.0.1:$port"
$env:ND_OLLAMA_EXE    = $ol
$env:HF_HOME          = Join-Path $root "speech\hf"
$env:ND_VOICES_DIR    = Join-Path $root "speech\voices"
$env:ND_WHISPER_DIR   = Join-Path $root "speech\whisper"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:ND_BROWSER_EXE     = Join-Path $rt "chromium\chrome-win64\chrome.exe"
$env:ND_BROWSER_PROFILE = Join-Path $data "browser\windows"
$env:ND_PORT          = "$(Free-Port 7810 20)"

$args_ = @("`"$app`"") + $(if ($Headless) { @("--headless") } else { @() })
Write-Host "Philibert Code -> http://localhost:$($env:ND_PORT)"
try {
    $p = Start-Process -FilePath $py -ArgumentList $args_ -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $logs "philibert-code.log") -RedirectStandardError (Join-Path $logs "philibert-code.err.log")
    $p.WaitForExit()
} finally {
    if ($started -and -not $started.HasExited) {
        & taskkill.exe /PID $started.Id /T /F | Out-Null           # /T: its model runners too
        Write-Host "Stopped the Ollama this start began"
    }
}
