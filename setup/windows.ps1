# Philibert by Esteef.Ai - Windows.
#
# Everything lives in this folder: its own Python, its own Ollama, its own models
# and data. Nothing is installed on the computer and nothing listens beyond it.
# The first start downloads what the drive needs (once, so it needs the Internet);
# every start after that runs offline.
#
# The user sees one window: "Setting up Philibert" with a progress bar on the
# first start, a short "Starting Philibert" on every start after. The work runs
# in a background runspace so the window never freezes; everything it does is
# written to data\logs\setup.log.
param([switch]$Full)     # -Full opens the full interface instead of the simple view
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$root = Split-Path (Split-Path $PSCommandPath -Parent) -Parent
$rt   = Join-Path $root "runtime\win-x64"
$data = Join-Path $root "data"
$logs = Join-Path $data "logs"
New-Item -ItemType Directory -Force $logs | Out-Null

function Say-Box($text, $title, $icon) {
    [void][System.Windows.Forms.MessageBox]::Show($text, $title, "OK", $icon)
}

# -- one Philibert per drive ---------------------------------------------------
# A second double-click would run setup twice against the same folders and the
# two would fight over files. Windows releases this lock by itself when the
# process ends, even after a crash.
$lockPath = Join-Path $root "runtime\.philibert.lock"
New-Item -ItemType Directory -Force (Split-Path $lockPath) | Out-Null
try {
    $script:driveLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    Say-Box "Philibert is already starting or running from this drive.`n`nIts window opens by itself - the first start can take a while." "Philibert" "Information"
    exit 0
}

# -- the drive's format: say so plainly instead of failing halfway --------------
try { $fs = (Get-Volume -FilePath $root -ErrorAction Stop).FileSystemType } catch { $fs = "" }
if ($fs -match "^FAT32$|^FAT$") {
    Say-Box "This drive is formatted FAT32, which cannot hold files over 4 GB - and every AI model is bigger.`n`nBack up the drive, reformat it as exFAT (Disk Management), and start Philibert again." "Philibert - drive format" "Warning"
    exit 1
}
if ($fs -match "^ReFS$") {
    Say-Box "This drive is formatted ReFS, which Philibert does not support.`n`nBack up the drive, reformat it as exFAT (Disk Management), and start Philibert again." "Philibert - drive format" "Warning"
    exit 1
}

# -- what this start has to do -------------------------------------------------
$cfg = @{
    Root = $root; Rt = $rt; Data = $data; Full = [bool]$Full
    Dl   = Join-Path $root "runtime\_download"
    Py   = Join-Path $rt "python\python.exe"
    Ol   = Join-Path $rt "ollama\ollama.exe"
    Cr   = Join-Path $rt "chromium\chrome-win64\chrome.exe"
    App  = Join-Path $root "app\NeuralDock_launcher.py"
    Log  = Join-Path $logs "setup.log"
    AppLog = Join-Path $logs "philibert.log"
    Tar  = Join-Path $env:SystemRoot "System32\tar.exe"
    FsNote = $(if ($fs -eq "NTFS") { "This drive is NTFS: it works on Windows, but a Mac can only read it." } else { "" })
    # Pinned: what this version of Philibert was tested with.
    PyUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.11.17%2B20261003-x86_64-pc-windows-msvc-install_only.tar.gz"
    OlVer = "v0.40.4"
    OlUrl = "https://github.com/ollama/ollama/releases/download/v0.40.4/ollama-windows-amd64.zip"
    # The window: Chrome for Testing, Google's pinned Chromium builds, run from the drive.
    CrVer = "156.0.8078.47"
    CrUrl = "https://storage.googleapis.com/chrome-for-testing-public/156.0.8078.47/win64/chrome-win64.zip"
    # The whole tested set, dependencies included, so a new release cannot slip in.
    Pkgs = @("psutil==7.2.2", "websockets==15.0.1", "pywebview==6.2.1", "pythonnet==3.1.0",
             "clr_loader==0.3.1", "cffi==2.1.1", "pycparser==3.0", "bottle==0.13.4",
             "proxy_tools==0.1.0", "typing_extensions==4.15.0",
             # speech: Whisper (listening) and Piper (speaking), both on the CPU
             "faster-whisper==1.2.1", "ctranslate2==4.8.1", "av==17.1.0", "tokenizers==0.22.2",
             "huggingface_hub==1.20.1", "piper-tts==1.6.0", "onnxruntime==1.28.0", "numpy==2.4.4")
}
function Stamp-Is($file, $value) { (Test-Path $file) -and ((Get-Content $file -Raw).Trim() -eq $value) }
$steps = New-Object System.Collections.ArrayList
if (-not (Test-Path (Join-Path $rt "python\.philibert-ready"))) {
    [void]$steps.Add(@{ Id = "python";   Title = "Getting Python for this drive";              Weight = 3 }) }
if (-not (Stamp-Is (Join-Path $rt "python\.philibert-packages") ($cfg.Pkgs -join " "))) {
    [void]$steps.Add(@{ Id = "packages"; Title = "Installing the app's building blocks";       Weight = 14 }) }
if (-not (Stamp-Is (Join-Path $rt "ollama\.philibert-version") $cfg.OlVer)) {
    [void]$steps.Add(@{ Id = "ollama";   Title = "Getting Ollama, which runs the AI models";   Weight = 30 }) }
if (-not (Stamp-Is (Join-Path $rt "chromium\.philibert-version") $cfg.CrVer)) {
    [void]$steps.Add(@{ Id = "chromium"; Title = "Getting Philibert's window";                 Weight = 10 }) }
[void]$steps.Add(@{ Id = "models"; Title = "Checking the AI models and voices";                Weight = 20 })
[void]$steps.Add(@{ Id = "start";  Title = "Starting Philibert";                               Weight = 4 })
$firstStart = $steps.Count -gt 2

$sync = [hashtable]::Synchronized(@{
    Step = 0; StepPct = 0.0; Detail = ""; Error = ""; Ready = $false; Done = $false
    Cancel = $false; ChildPid = 0; OllamaPid = 0; OllamaPort = 0; Title = ""
})

# -- the work, on its own runspace ---------------------------------------------
$work = {
    param($cfg, $steps, $sync)
    $ErrorActionPreference = "Stop"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    # The log is shared: anyone may read it (Notepad, antivirus) while setup writes,
    # and a line that cannot be written is dropped - logging never stops setup.
    function Log($m) {
        try {
            $f = [IO.File]::Open($cfg.Log, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
            $b = [Text.Encoding]::UTF8.GetBytes(("{0:yyyy-MM-dd HH:mm:ss}  {1}`r`n" -f (Get-Date), $m))
            $f.Write($b, 0, $b.Length); $f.Close()
        } catch {}
    }
    function Halt($m) { throw $m }
    function Check-Cancel { if ($sync.Cancel) { throw "__cancel__" } }

    # Download with progress; resumes a part-file left by an earlier start.
    function Download($url, $out, $label) {
        for ($try = 1; $try -le 8; $try++) {
            Check-Cancel
            try {
                $have = 0; if (Test-Path $out) { $have = (Get-Item $out).Length }
                $req = [Net.HttpWebRequest]::Create($url)
                $req.UserAgent = "Philibert-setup"; $req.Timeout = 30000; $req.ReadWriteTimeout = 60000
                if ($have -gt 0) { $req.AddRange([long]$have) }
                $resp = $req.GetResponse()
                if ($have -gt 0 -and [int]$resp.StatusCode -ne 206) { $have = 0 }
                $total = $have + $resp.ContentLength
                $mode = $(if ($have -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create })
                $fsOut = [IO.File]::Open($out, $mode, [IO.FileAccess]::Write)
                $in = $resp.GetResponseStream()
                $buf = New-Object byte[] 1048576
                $done = $have; $t0 = Get-Date; $start = $have
                try {
                    while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                        Check-Cancel
                        $fsOut.Write($buf, 0, $n); $done += $n
                        $secs = [Math]::Max(0.5, ((Get-Date) - $t0).TotalSeconds)
                        $sync.StepPct = $(if ($total -gt 0) { $done / $total } else { -1 })
                        $sync.Detail = "{0} - {1:N0} of {2:N0} MB  ({3:N1} MB/s)" -f $label, ($done / 1MB), ($total / 1MB), ((($done - $start) / 1MB) / $secs)
                    }
                } finally { $fsOut.Close(); $in.Close(); $resp.Close() }
                if ($total -gt 0 -and (Get-Item $out).Length -lt $total) { throw "the download was cut short" }
                Log "downloaded $url"
                return
            } catch {
                if ("$_" -eq "__cancel__") { throw }
                Log "download attempt $try of $url failed: $_"
                $sync.Detail = "$label - connection trouble, trying again ($try of 8)"
                Start-Sleep -Seconds ([Math]::Min(20, 3 * $try))
            }
        }
        Halt "Could not download $label. The first start needs the Internet - connect and start Philibert again; it continues where it stopped."
    }

    function Unpack($file, $into, $expect, $label) {
        $sync.StepPct = -1; $sync.Detail = "$label - unpacking"
        New-Item -ItemType Directory -Force $into | Out-Null
        # -m: exFAT rejects some of the times stored in the archive.
        $p = Start-Process -FilePath $cfg.Tar -ArgumentList @("-xmf", "`"$file`"", "-C", "`"$into`"") -NoNewWindow -PassThru -Wait
        if ($p.ExitCode -ne 0 -or -not (Test-Path $expect)) { Halt "Could not unpack $label." }
        Remove-Item $file -ErrorAction SilentlyContinue
    }

    # Run a program, hidden, feeding its output to the log and the detail line.
    function Run-Lines($exe, $argList, $onLine) {
        $psi = New-Object Diagnostics.ProcessStartInfo $exe
        $psi.Arguments = $argList; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
        foreach ($k in @("PYTHONNOUSERSITE", "TEMP", "TMP", "OLLAMA_HOST", "OLLAMA_MODELS", "HF_HOME",
                         "ND_VOICES_DIR", "ND_WHISPER_DIR", "ND_OLLAMA_URL", "HF_HUB_DISABLE_TELEMETRY",
                         "PYTHONIOENCODING")) {
            $v = [Environment]::GetEnvironmentVariable($k); if ($v) { $psi.EnvironmentVariables[$k] = $v }
        }
        $p = [Diagnostics.Process]::Start($psi)
        $sync.ChildPid = $p.Id
        $errTask = $p.StandardError.ReadToEndAsync()
        while (-not $p.StandardOutput.EndOfStream) {
            $line = $p.StandardOutput.ReadLine()
            if ($line) { Log $line; & $onLine $line }
            if ($sync.Cancel) { try { $p.Kill() } catch {}; throw "__cancel__" }
        }
        $p.WaitForExit()
        $err = $errTask.Result
        if ($err) { Log $err }
        $sync.ChildPid = 0
        return @{ Code = $p.ExitCode; Err = $err }
    }

    # The first free port from $from up: two Philibert drives (or anything else on
    # the usual port) must never answer for each other.
    function Free-Port($from, $count) {
        for ($p = $from; $p -lt $from + $count; $p++) {
            try {
                $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $p)
                $l.Start(); $l.Stop(); return $p
            } catch {}
        }
        Halt "No free network port for Philibert on this computer (tried $from-$($from + $count - 1))."
    }

    $env:PYTHONNOUSERSITE = "1"           # never pick up this computer's own Python packages
    $env:PYTHONIOENCODING = "utf-8"
    $env:TEMP = $env:TMP = Join-Path $cfg.Root "runtime\_download\tmp"   # pip's scratch stays on the drive
    New-Item -ItemType Directory -Force $env:TEMP, $cfg.Dl | Out-Null

    try {
        Log "---- start ($($steps.Count) steps) ----"
        for ($i = 0; $i -lt $steps.Count; $i++) {
            $s = $steps[$i]; $sync.Step = $i; $sync.StepPct = 0; $sync.Detail = ""
            Check-Cancel
            switch ($s.Id) {
                "python" {
                    $f = Join-Path $cfg.Dl "python.tar.gz"
                    Download $cfg.PyUrl $f "Python (about 30 MB)"
                    Unpack $f $cfg.Rt $cfg.Py "Python"
                    Set-Content -Path (Join-Path $cfg.Rt "python\.philibert-ready") -Value "ok" -Encoding ascii
                }
                "packages" {
                    $total = 40.0; $seen = 0
                    $script:pkgSeen = 0
                    $argList = "-m pip install --no-cache-dir --disable-pip-version-check --no-warn-script-location --progress-bar off " + ($cfg.Pkgs -join " ")
                    $r = Run-Lines $cfg.Py $argList {
                        param($line)
                        if ($line -match "^(Collecting|Requirement already satisfied)\s+(\S+)") {
                            $script:pkgSeen++
                            $sync.StepPct = [Math]::Min(0.9, $script:pkgSeen / 40.0)
                            $sync.Detail = "Getting " + ($Matches[2] -replace "[=<>].*$", "")
                        } elseif ($line -match "^Installing collected packages") {
                            $sync.StepPct = 0.93; $sync.Detail = "Installing onto the drive"
                        } elseif ($line -match "^Successfully installed") {
                            $sync.StepPct = 1.0
                        }
                    }
                    if ($r.Code -ne 0) {
                        $why = $(if ($r.Err -match "WinError 32|being used by another process") { " Another program was using the drive's files - close it and start Philibert again." }
                                 elseif ($r.Err -match "Could not find a version|No matching distribution|Network|connection") { " Check the Internet connection and start Philibert again." }
                                 else { " The details are in data\logs\setup.log." })
                        Halt ("Could not install the app's building blocks." + $why)
                    }
                    Set-Content -Path (Join-Path $cfg.Rt "python\.philibert-packages") -Value ($cfg.Pkgs -join " ") -Encoding ascii
                }
                "ollama" {
                    $f = Join-Path $cfg.Dl "ollama.zip"
                    Download $cfg.OlUrl $f "Ollama (about 1.5 GB)"
                    Unpack $f (Join-Path $cfg.Rt "ollama") $cfg.Ol "Ollama"
                    Set-Content -Path (Join-Path $cfg.Rt "ollama\.philibert-version") -Value $cfg.OlVer -Encoding ascii
                }
                "chromium" {
                    $f = Join-Path $cfg.Dl "chromium.zip"
                    Download $cfg.CrUrl $f "the window (about 170 MB)"
                    Unpack $f (Join-Path $cfg.Rt "chromium") $cfg.Cr "the window"
                    Set-Content -Path (Join-Path $cfg.Rt "chromium\.philibert-version") -Value $cfg.CrVer -Encoding ascii
                }
                "models" {
                    # data: created once, never overwritten
                    New-Item -ItemType Directory -Force (Join-Path $cfg.Data "vault"), (Join-Path $cfg.Data "exports"), (Join-Path $cfg.Root "secrets") | Out-Null
                    $conf = Join-Path $cfg.Data "neuraldock_config.json"
                    if (-not (Test-Path $conf)) { Copy-Item (Join-Path $cfg.Root "setup\default_config.json") $conf }
                    # a new drive's vault starts with a few welcome notes - never over the user's own
                    $vault = Join-Path $cfg.Data "vault"
                    if (-not (Get-ChildItem $vault -Recurse -Filter *.md -ErrorAction SilentlyContinue | Select-Object -First 1)) {
                        Copy-Item (Join-Path $cfg.Root "setup\welcome_vault\*") $vault -Recurse -Force
                        Log "welcome notes added to the empty vault"
                    }

                    $sync.OllamaPort = Free-Port 11435 20
                    $env:OLLAMA_MODELS          = Join-Path $cfg.Root "models"
                    $env:OLLAMA_HOST            = "127.0.0.1:$($sync.OllamaPort)"
                    $env:ND_OLLAMA_URL          = "http://127.0.0.1:$($sync.OllamaPort)"
                    $env:OLLAMA_FLASH_ATTENTION = "1"
                    $env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
                    $env:OLLAMA_NOPRUNE         = "1"     # never delete model files on start
                    $env:OLLAMA_LOAD_TIMEOUT    = "30m"   # a USB hard drive can take minutes to load a big model
                    # Speech models and voices live on the drive too (Whisper downloads through
                    # Hugging Face's cache, which would otherwise land in the user's profile).
                    $env:HF_HOME        = Join-Path $cfg.Root "speech\hf"
                    $env:ND_VOICES_DIR  = Join-Path $cfg.Root "speech\voices"
                    # Whisper as plain folders: exFAT cannot hold the Hugging Face cache's symlinks.
                    $env:ND_WHISPER_DIR = Join-Path $cfg.Root "speech\whisper"
                    $env:HF_HUB_DISABLE_TELEMETRY = "1"

                    $sync.StepPct = -1; $sync.Detail = "Starting Ollama"
                    $o = Start-Process -FilePath $cfg.Ol -ArgumentList "serve" -WindowStyle Hidden -PassThru
                    $sync.OllamaPid = $o.Id
                    $up = $false
                    foreach ($k in 1..60) {
                        if ($o.HasExited) { break }
                        try { Invoke-RestMethod "http://127.0.0.1:$($sync.OllamaPort)/api/version" -TimeoutSec 2 | Out-Null; $up = $true; break }
                        catch { Start-Sleep -Milliseconds 500 }
                    }
                    if (-not $up) { Halt "Ollama, which runs the AI models, did not start. The details are in data\logs\setup.log." }

                    # A model that suits this computer, the notes embedder and the vision model - only if missing.
                    $sync.Detail = "Checking what is on the drive"
                    $r = Run-Lines $cfg.Py ("`"" + (Join-Path $cfg.Root "app\nd_philibert.py") + "`" --first-run") {
                        param($line)
                        $t = $line.Trim()
                        if ($t -match "(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*GB") {       # "qwen3:8b: 2.5 / 5.2 GB"
                            $sync.StepPct = [Math]::Min(1.0, [double]$Matches[1] / [Math]::Max(0.01, [double]$Matches[2]))
                            $sync.Title = "Getting the AI models"
                        } elseif ($t -match "(\d{1,3})(?:\.\d+)?%") { $sync.StepPct = [double]$Matches[1] / 100 }
                        elseif ($t -match "^(Downloading the voice|Getting the speech model)") { $sync.Title = "Getting the voices" }
                        if ($t) { $sync.Detail = $(if ($t.Length -gt 90) { $t.Substring(0, 90) + "..." } else { $t }) }
                    }
                    if ($r.Code -ne 0) {
                        Log "first-run reported problems; Philibert starts anyway"
                        $sync.Detail = "Some downloads did not finish - pick a model in the list later to finish it."
                        Start-Sleep -Seconds 2
                    }
                }
                "start" {
                    $sync.StepPct = -1; $sync.Detail = "Opening the window"
                    $env:HF_HUB_OFFLINE = "1"     # from here on, speech uses only what is on the drive
                    $env:PHILIBERT_ROOT = $cfg.Root
                    $env:ND_PORTABLE    = "1"
                    $env:ND_DATA_DIR    = $cfg.Data
                    $env:ND_OLLAMA_EXE  = $cfg.Ol
                    $ndPort = Free-Port 7790 20
                    $env:ND_PORT        = "$ndPort"
                    $env:ND_START_PATH  = $(if ($cfg.Full) { "/full" } else { "" })
                    # The drive's Chromium, with its profile on the drive: nothing lands in the PC's browser.
                    $env:ND_BROWSER_EXE     = $cfg.Cr
                    $env:ND_BROWSER_PROFILE = Join-Path $cfg.Data "browser\windows"
                    $app = Start-Process -FilePath $cfg.Py -ArgumentList "`"$($cfg.App)`"" -WindowStyle Hidden -PassThru `
                        -RedirectStandardOutput $cfg.AppLog -RedirectStandardError ($cfg.AppLog + ".err")
                    $sync.ChildPid = $app.Id
                    foreach ($k in 1..240) {
                        if ($app.HasExited) { Halt "Philibert stopped while starting. The details are in data\logs\philibert.log." }
                        # the port was free when we picked it, so whoever answers now is ours
                        try { Invoke-WebRequest "http://127.0.0.1:$ndPort/api/status" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
                        catch { Start-Sleep -Milliseconds 500 }
                    }
                    $sync.StepPct = 1.0; $sync.Ready = $true
                    Log "Philibert is up"
                    $app.WaitForExit()                 # until its window is closed
                    Log "Philibert closed"
                }
            }
        }
    } catch {
        if ("$_" -ne "__cancel__") { $sync.Error = "$_"; Log "STOPPED: $_" } else { Log "cancelled by the user" }
        if ($sync.ChildPid) { & taskkill.exe /PID $sync.ChildPid /T /F *> $null; $sync.ChildPid = 0 }
    } finally {
        $sync.Done = $true
    }
}

# -- the window ----------------------------------------------------------------
$navy = [Drawing.Color]::FromArgb(15, 23, 42); $line = [Drawing.Color]::FromArgb(30, 48, 84)
$cyan = [Drawing.Color]::FromArgb(0, 229, 255); $txt = [Drawing.Color]::FromArgb(215, 227, 244)
$dim  = [Drawing.Color]::FromArgb(142, 163, 196); $red = [Drawing.Color]::FromArgb(255, 107, 107)

$form = New-Object Windows.Forms.Form
$form.Text = "Philibert"; $form.ClientSize = New-Object Drawing.Size(560, 300)
$form.FormBorderStyle = "FixedSingle"; $form.MaximizeBox = $false; $form.StartPosition = "CenterScreen"
$form.BackColor = $navy; $form.Font = New-Object Drawing.Font("Segoe UI", 9.5)
$hdrPath = Join-Path $PSScriptRoot "assets\header.png"
if (Test-Path $hdrPath) {
    $img = [Drawing.Image]::FromFile($hdrPath)
    $pic = New-Object Windows.Forms.PictureBox
    $pic.Image = $img; $pic.SetBounds(0, 0, 560, 112); $form.Controls.Add($pic)
    try { $form.Icon = [Drawing.Icon]::FromHandle(([Drawing.Bitmap]$img).Clone((New-Object Drawing.Rectangle(26, 22, 68, 68)), $img.PixelFormat).GetHicon()) } catch {}
}
function New-Label($x, $y, $w, $h, $color, $font) {
    $l = New-Object Windows.Forms.Label
    $l.SetBounds($x, $y, $w, $h); $l.ForeColor = $color; $l.BackColor = $navy
    if ($font) { $l.Font = $font }
    $form.Controls.Add($l); return $l
}
$title  = New-Label 28 128 504 26 $txt (New-Object Drawing.Font("Segoe UI Semibold", 13))
$stepL  = New-Label 28 156 504 20 $dim $null
$title.Text = $(if ($firstStart) { "Setting up Philibert on this drive" } else { "Starting Philibert" })

# progress bars, drawn in the brand colours
function New-Bar($y, $h) {
    $track = New-Object Windows.Forms.Panel
    $track.SetBounds(28, $y, 504, $h); $track.BackColor = $line
    $fill = New-Object Windows.Forms.Panel
    $fill.SetBounds(0, 0, 0, $h); $fill.BackColor = $cyan
    $track.Controls.Add($fill); $form.Controls.Add($track)
    return @{ Track = $track; Fill = $fill }
}
$bar1 = New-Bar 184 10
$bar2 = New-Bar 200 4
$detail = New-Label 28 212 504 20 $dim (New-Object Drawing.Font("Consolas", 9))
$foot   = New-Label 28 252 360 34 $dim (New-Object Drawing.Font("Segoe UI", 8.5))
$foot.Text = $(if ($firstStart) { "The first start downloads about 2 GB onto the drive, once. After that Philibert runs offline." + $(if ($cfg.FsNote) { " " + $cfg.FsNote } else { "" }) } else { $cfg.FsNote })

$btn = New-Object Windows.Forms.Button
$btn.SetBounds(432, 254, 100, 30); $btn.Text = "Cancel"; $btn.FlatStyle = "Flat"
$btn.ForeColor = $txt; $btn.BackColor = $navy; $btn.FlatAppearance.BorderColor = $line
$form.Controls.Add($btn)
$logBtn = New-Object Windows.Forms.Button
$logBtn.SetBounds(320, 254, 104, 30); $logBtn.Text = "Open the log"; $logBtn.FlatStyle = "Flat"; $logBtn.Visible = $false
$logBtn.ForeColor = $txt; $logBtn.BackColor = $navy; $logBtn.FlatAppearance.BorderColor = $line
$form.Controls.Add($logBtn)
$logBtn.Add_Click({ Start-Process notepad.exe $cfg.Log })

$script:closing = $false
$btn.Add_Click({ $form.Close() })
$form.Add_FormClosing({
    param($s, $e)
    if ($sync.Done -or $sync.Error -or $sync.Ready -or $script:closing) { return }
    $ans = [Windows.Forms.MessageBox]::Show("Stop setting up Philibert?`n`nWhat is already downloaded stays on the drive; the next start continues from there.", "Philibert", "YesNo", "Question")
    if ($ans -ne "Yes") { $e.Cancel = $true; return }
    $sync.Cancel = $true
    if ($sync.ChildPid) { & taskkill.exe /PID $sync.ChildPid /T /F *> $null }
})

$weights = 0; foreach ($s in $steps) { $weights += $s.Weight }
$script:sweep = 0
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 120
$timer.Add_Tick({
    if ($sync.Error) {
        $timer.Stop()
        $title.Text = "Philibert stopped"; $title.ForeColor = $red
        $stepL.Text = ""; $detail.Text = ""
        $foot.SetBounds(28, 184, 504, 64); $foot.ForeColor = $txt; $foot.Text = $sync.Error
        $bar1.Track.Visible = $false; $bar2.Track.Visible = $false
        $btn.Text = "Close"; $logBtn.Visible = $true
        return
    }
    $i = [Math]::Min($sync.Step, $steps.Count - 1)
    $stepL.Text = "Step {0} of {1}:  {2}" -f ($i + 1), $steps.Count, $steps[$i].Title
    $doneW = 0; for ($k = 0; $k -lt $i; $k++) { $doneW += $steps[$k].Weight }
    $p = [double]$sync.StepPct
    $within = $(if ($p -ge 0) { $p } else { 0.35 })
    $bar1.Fill.Width = [int](504 * [Math]::Min(1.0, ($doneW + $steps[$i].Weight * $within) / $weights))
    if ($p -ge 0) {
        $bar2.Fill.Left = 0; $bar2.Fill.Width = [int](504 * [Math]::Min(1.0, $p))
    } else {                                   # no size to measure: a moving segment
        $script:sweep = ($script:sweep + 14) % 640
        $bar2.Fill.Width = 120; $bar2.Fill.Left = $script:sweep - 120
    }
    $detail.Text = $sync.Detail
    if ($sync.Title -and $title.Text -ne $sync.Title) { $title.Text = $sync.Title }
    if ($sync.Ready) { $timer.Stop(); $script:closing = $true; $form.Close() }
    elseif ($sync.Done) { $timer.Stop(); $script:closing = $true; $form.Close() }
})

$rs = [RunspaceFactory]::CreateRunspace(); $rs.ApartmentState = "STA"; $rs.Open()
$ps = [PowerShell]::Create(); $ps.Runspace = $rs
[void]$ps.AddScript($work).AddArgument($cfg).AddArgument($steps).AddArgument($sync)
$handle = $ps.BeginInvoke()

$form.Add_Shown({ $timer.Start(); $form.Activate() })
# Development only: PHILIBERT_SETUP_SNAPSHOT=<folder> saves a picture of this window
# every few seconds, so the setup flow can be checked without watching the screen.
if ($env:PHILIBERT_SETUP_SNAPSHOT) {
    $script:snapN = 0
    $snapTimer = New-Object Windows.Forms.Timer
    $snapTimer.Interval = 4000
    $snapTimer.Add_Tick({
        $bmp = New-Object Drawing.Bitmap($form.Width, $form.Height)
        $form.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
        $bmp.Save((Join-Path $env:PHILIBERT_SETUP_SNAPSHOT ("setup_{0:D2}.png" -f $script:snapN)))
        $bmp.Dispose(); $script:snapN++
    })
    $form.Add_Shown({ $snapTimer.Start() })
}
try {
    [void]$form.ShowDialog()
    # The window is up (or setup was stopped): wait for Philibert to close.
    while (-not $sync.Done) { Start-Sleep -Milliseconds 400 }
} finally {
    # /T takes the model runners (llama-server) down too; otherwise they keep
    # holding GPU memory after Philibert has closed.
    if ($sync.OllamaPid) { & taskkill.exe /PID $sync.OllamaPid /T /F *> $null }
    try { $ps.EndInvoke($handle) } catch {}
    $ps.Dispose(); $rs.Close()
}
