# Philibert by Esteef.Ai - Windows.
#
# Everything lives in this folder: its own Python, its own Ollama, its own models
# and data. Nothing is installed on the computer and nothing listens beyond it.
# The first start downloads what the drive needs (once, so it needs the Internet);
# every start after that runs offline.
param([switch]$Full)     # -Full opens the full interface instead of the simple view
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$root = Split-Path (Split-Path $PSCommandPath -Parent) -Parent
$rt   = Join-Path $root "runtime\win-x64"
$dl   = Join-Path $root "runtime\_download"
$py   = Join-Path $rt "python\python.exe"
$ol   = Join-Path $rt "ollama\ollama.exe"
$app  = Join-Path $root "app\NeuralDock_launcher.py"

# Pinned: what this version of Philibert was tested with.
$PY_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.11.17%2B20261003-x86_64-pc-windows-msvc-install_only.tar.gz"
$OL_VER = "v0.40.4"
$OL_URL = "https://github.com/ollama/ollama/releases/download/$OL_VER/ollama-windows-amd64.zip"
# The whole tested set, dependencies included, so a new release cannot slip in.
$PKGS   = @("psutil==7.2.2", "websockets==15.0.1", "pywebview==6.2.1", "pythonnet==3.1.0",
            "clr_loader==0.3.1", "cffi==2.1.1", "pycparser==3.0", "bottle==0.13.4",
            "proxy_tools==0.1.0", "typing_extensions==4.15.0")

# Windows' own tools by full path: with Git's tools on the PATH, "tar" can be GNU
# tar, which reads "J:\..." as a remote host and fails.
$TAR  = Join-Path $env:SystemRoot "System32\tar.exe"
$CURL = Join-Path $env:SystemRoot "System32\curl.exe"

function Step($m) { Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }
function Fail($m) {
    Write-Host ""; Write-Host "!! $m" -ForegroundColor Red
    Read-Host "Press Enter to close"; exit 1
}
function Fetch($url, $out) {
    # curl.exe ships with Windows 10 and 11; it resumes (-C -) if a download was cut off.
    & $CURL -L --fail --retry 10 --retry-all-errors --retry-delay 3 -C - -o $out $url
    if ($LASTEXITCODE -ne 0) {
        Fail "Could not download $([IO.Path]::GetFileName($out)). The first start needs the Internet - connect and run this again."
    }
}

Write-Host "Philibert by Esteef.Ai - $root"

# -- first run: Python ---------------------------------------------------------
if (-not (Test-Path $py)) {
    Step "First start: getting Python for this drive (about 30 MB)"
    New-Item -ItemType Directory -Force $dl, $rt | Out-Null
    Fetch $PY_URL "$dl\python.tar.gz"
    & $TAR -xzf "$dl\python.tar.gz" -C $rt          # -> runtime\win-x64\python
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Fail "Could not unpack Python." }
    Remove-Item "$dl\python.tar.gz" -ErrorAction SilentlyContinue
}
$env:PYTHONNOUSERSITE = "1"     # never pick up this computer's own Python packages
# pip unpacks through TEMP; keep even that on the drive.
$env:TEMP = $env:TMP = Join-Path $root "runtime/_download/tmp"
New-Item -ItemType Directory -Force $env:TEMP | Out-Null

$stamp = Join-Path $rt "python\.philibert-packages"
$want  = $PKGS -join " "
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $want) {
    Step "Installing the app's Python packages onto the drive"
    & $py -m pip install --no-cache-dir --disable-pip-version-check --no-warn-script-location @PKGS
    if ($LASTEXITCODE -ne 0) { Fail "Could not install the Python packages. The first start needs the Internet." }
    Set-Content -Path $stamp -Value $want -Encoding ascii
}

# -- first run: Ollama ---------------------------------------------------------
$olStamp = Join-Path $rt "ollama\.philibert-version"
$olOld   = (Test-Path $olStamp) -and ((Get-Content $olStamp -Raw).Trim() -ne $OL_VER)
if (-not (Test-Path $ol) -or $olOld) {
    Step "First start: getting Ollama, which runs the AI models (about 1.5 GB)"
    New-Item -ItemType Directory -Force $dl, (Join-Path $rt "ollama") | Out-Null
    Fetch $OL_URL "$dl\ollama.zip"
    & $TAR -xf "$dl\ollama.zip" -C (Join-Path $rt "ollama")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ol)) { Fail "Could not unpack Ollama." }
    Set-Content -Path $olStamp -Value $OL_VER -Encoding ascii
    Remove-Item "$dl\ollama.zip" -ErrorAction SilentlyContinue
}

# -- data: created once, never overwritten -------------------------------------
$data = Join-Path $root "data"
New-Item -ItemType Directory -Force (Join-Path $data "vault"), (Join-Path $data "exports"), (Join-Path $root "secrets") | Out-Null
$cfg = Join-Path $data "neuraldock_config.json"
if (-not (Test-Path $cfg)) { Copy-Item (Join-Path $PSScriptRoot "default_config.json") $cfg }

# -- run -----------------------------------------------------------------------
$env:OLLAMA_MODELS          = Join-Path $root "models"
$env:OLLAMA_HOST            = "127.0.0.1:11435"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
$env:OLLAMA_NOPRUNE         = "1"     # never delete model files on start
$env:OLLAMA_LOAD_TIMEOUT    = "30m"   # a USB hard drive can take minutes to load a big model

$env:PHILIBERT_ROOT = $root
$env:ND_PORTABLE    = "1"
$env:ND_DATA_DIR    = $data
$env:ND_OLLAMA_URL  = "http://127.0.0.1:11435"
$env:ND_OLLAMA_EXE  = $ol
$env:ND_PORT        = "7790"
$env:ND_START_PATH  = $(if ($Full) { "/full" } else { "" })

$ollama = Start-Process -FilePath $ol -ArgumentList "serve" -WindowStyle Hidden -PassThru
try {
    $up = $false
    foreach ($i in 1..60) {
        try { Invoke-RestMethod "http://127.0.0.1:11435/api/version" -TimeoutSec 2 | Out-Null; $up = $true; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $up) { Fail "Ollama did not start." }

    # A model that suits this computer, and the notes embedder - only if missing.
    & $py (Join-Path $root "app\nd_philibert.py") --first-run
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Some models could not be downloaded. Philibert will start anyway;"
        Write-Host "connect to the Internet and pick a model in the list to download it."
    }

    & $py $app
}
finally {
    # /T takes the model runners (llama-server) down too; otherwise they keep
    # holding GPU memory after Philibert has closed.
    if ($ollama -and -not $ollama.HasExited) { & taskkill.exe /PID $ollama.Id /T /F *> $null }
}
