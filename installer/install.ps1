<#
  Print Studio setup: everything the app needs, in this folder.

    1. Check the computer (Windows, NVIDIA RTX card, free disk space)
    2. Python 3.11 (installed for this user if missing)
    3. The app's own Python environment
    4. The 3D engine (WanGP, pinned version) and its environment
    5. The idea helper (Ollama + Gemma), optional
    6. All AI models, by running each 3D step once (also proves the GPU works)
    7. Desktop and Start-menu shortcuts

  Safe to run again: finished steps are skipped, so an interrupted install just continues.

    setup.bat                      normal install
    setup.bat -NoLLM               without the idea helper (ideas are then used as written)
    setup.bat -WanGPDir D:\Wan2GP  use a WanGP you already have instead of installing one
    setup.bat -SkipModels          don't download models now (they download on first use)
#>
param(
    [switch]$NoLLM,
    [switch]$SkipModels,
    [string]$WanGPDir = "",
    [switch]$NoShortcuts,
    [switch]$FromSetupExe
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"        # Invoke-WebRequest is 10x slower with the progress bar
$env:PIP_DEFAULT_TIMEOUT = "120"                 # slow or flaky connections: wait longer, retry more
$env:PIP_RETRIES = "10"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$WanGPCommit = "665e4cfdf94c6478fd1357458a3c50f86a161d7d"     # tested with this WanGP version
$PythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$OllamaUrl = "https://ollama.com/download/OllamaSetup.exe"
$LlmModel = "gemma4:12b"
$NeedGB = 60
$Downloads = Join-Path $Root "engine\downloads"
$LogFile = Join-Path $Root "install.log"

Start-Transcript -Path $LogFile -Append | Out-Null
$Host.UI.RawUI.WindowTitle = "Print Studio setup"

function Step($n, $text) { Write-Host ""; Write-Host "==== [$n/7] $text ====" -ForegroundColor Cyan }
function Info($text) { Write-Host "  $text" }
function Warn($text) { Write-Host "  ! $text" -ForegroundColor Yellow }
function Fail($text) {
    Write-Host ""
    Write-Host "  X $text" -ForegroundColor Red
    Write-Host "  Run setup again to continue from here. Details: $LogFile"
    Stop-Transcript | Out-Null
    Read-Host "Press Enter to close"
    exit 1
}
function Run($exe, [string[]]$argv, $what) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit code $LASTEXITCODE)." }
}
function Download($url, $file) {
    if (Test-Path $file) { return }
    New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null
    Info "Downloading $url"
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile "$file.part" -UseBasicParsing; Move-Item "$file.part" $file; return }
        catch { Warn "Download attempt $i failed: $($_.Exception.Message)"; Start-Sleep 5 }
    }
    Fail "Could not download $url. Check the internet connection."
}

Write-Host ""
Write-Host "  Print Studio setup" -ForegroundColor Green
Write-Host "  Installs into: $Root"
Write-Host "  Needs about $NeedGB GB of disk and an internet connection. The first install takes 30-90 minutes,"
Write-Host "  mostly downloading AI models. You can close this window at any time and run setup again to continue."

# ---------------------------------------------------------------- 1. the computer
Step 1 "Checking this computer"
if ($Root -match " ") { Warn "The folder path has spaces. That usually works, but a path without spaces is safer." }
$gpu = $null
try { $gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1) } catch {}
if (-not $gpu) { Fail "No NVIDIA graphics card found (or its driver is missing). Print Studio needs an NVIDIA RTX card with 8 GB or more." }
$gpuName, $vram = $gpu.Split(",") | ForEach-Object { $_.Trim() }
Info "Graphics card: $gpuName ($([math]::Round([int]$vram / 1024)) GB)"
if ([int]$vram -lt 7500) { Warn "Less than 8 GB of graphics memory: the 3D steps may fail or be very slow." }
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Info "Memory: $ram GB"
if ($ram -lt 24) { Warn "Less than 32 GB of memory: the 3D steps may be slow." }
$drive = (Get-Item $Root).PSDrive
$freeGB = [math]::Round($drive.Free / 1GB)
Info "Free space on ${drive}: $freeGB GB"
$haveEngine = (Test-Path (Join-Path $Root "engine\Wan2GP\ckpts")) -or $WanGPDir
if ($freeGB -lt $NeedGB -and -not $haveEngine) { Fail "Not enough free space: $NeedGB GB needed on drive $drive." }

# ---------------------------------------------------------------- 2. Python 3.11
Step 2 "Python 3.11"
$launchers = @("$env:LOCALAPPDATA\Programs\Python\Launcher", "$env:WINDIR")
foreach ($d in $launchers) { if (Test-Path "$d\py.exe") { $env:PATH = "$d;$env:PATH" } }
function Find-Python {
    try { $p = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null); if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() } } catch {}
    $c = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    if (Test-Path $c) { return $c }
    return $null
}
$Py = Find-Python
if (-not $Py) {
    $pyExe = Join-Path $Downloads "python-3.11.9-amd64.exe"
    Download $PythonUrl $pyExe
    Info "Installing Python 3.11 for this user..."
    $p = Start-Process $pyExe -ArgumentList "/quiet InstallAllUsers=0 Include_launcher=1 InstallLauncherAllUsers=0 PrependPath=0 Include_test=0" -Wait -PassThru
    if ($p.ExitCode -ne 0) { Fail "Python setup failed (exit code $($p.ExitCode))." }
    foreach ($d in $launchers) { if (Test-Path "$d\py.exe") { $env:PATH = "$d;$env:PATH" } }
    $Py = Find-Python
    if (-not $Py) { Fail "Python 3.11 was installed but can't be found." }
}
Info "Python: $Py"

# ---------------------------------------------------------------- 3. the app
Step 3 "The app"
$AppPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $AppPy)) { Run $Py @("-m", "venv", (Join-Path $Root ".venv")) "Creating the app environment" }
& $AppPy -m pip install --disable-pip-version-check -q --upgrade pip    # nice to have, not required
Run $AppPy @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $Root "requirements.txt")) "Installing the app's libraries"
New-Item -ItemType Directory -Force (Join-Path $Root "jobs") | Out-Null
Info "App ready."

# ---------------------------------------------------------------- 4. the 3D engine
Step 4 "The 3D engine (WanGP)"
$settingsFile = Join-Path $Root "settings.json"
$settings = @{}
if (Test-Path $settingsFile) {
    (Get-Content $settingsFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
}
if ($WanGPDir) {
    if (-not (Test-Path (Join-Path $WanGPDir "env_venv\Scripts\python.exe"))) { Fail "$WanGPDir is not an installed WanGP (no env_venv)." }
    $Engine = (Resolve-Path $WanGPDir).Path
    $settings["wangp_dir"] = $Engine
    Info "Using the WanGP in $Engine"
} else {
    $Engine = Join-Path $Root "engine\Wan2GP"
    if (-not (Test-Path (Join-Path $Engine "wgp.py"))) {
        $zip = Join-Path $Downloads "Wan2GP-$WanGPCommit.zip"
        Download "https://github.com/deepbeepmeep/Wan2GP/archive/$WanGPCommit.zip" $zip
        Info "Unpacking..."
        $tmp = Join-Path $Root "engine\unpack"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive $zip $tmp
        Move-Item (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName $Engine
        Remove-Item -Recurse -Force $tmp
    }
    $EnginePy = Join-Path $Engine "env_venv\Scripts\python.exe"
    $ok = $false
    if (Test-Path $EnginePy) { try { & $EnginePy -c "import torch, mmgp" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch {} }
    if (-not $ok) {
        Info "Installing the engine's libraries (PyTorch with CUDA and more, several GB)..."
        Push-Location $Engine
        $hasTorch = $false
        if (Test-Path $EnginePy) { try { & $EnginePy -c "import torch" 2>$null; $hasTorch = ($LASTEXITCODE -eq 0) } catch {} }
        if ($hasTorch) {
            $code = 1                                # a previous run got past PyTorch: just finish the rest
        } else {
            & $Py setup.py install --env venv --auto
            $code = $LASTEXITCODE
        }
        if ($code -ne 0) {
            Warn "WanGP's installer stopped (exit code $code). Trying the core install without optional extras..."
            & $Py (Join-Path $PSScriptRoot "wangp_core.py")
            $code = $LASTEXITCODE
        }
        Pop-Location
        if ($code -ne 0) { Fail "Installing the 3D engine failed." }
    }
    $settings.Remove("wangp_dir")
}
Info "3D engine ready."

# ---------------------------------------------------------------- 5. the idea helper
Step 5 "The idea helper (Ollama + Gemma)"
if ($NoLLM) {
    Info "Skipped. Ideas are used as written when making pictures."
} else {
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama -and (Test-Path "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    if (-not $ollama) {
        $oExe = Join-Path $Downloads "OllamaSetup.exe"
        Download $OllamaUrl $oExe
        Info "Installing Ollama..."
        $p = Start-Process $oExe -ArgumentList "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES" -Wait -PassThru
        $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        if (-not (Test-Path $ollama)) { Warn "Ollama didn't install; skipping the idea helper." ; $ollama = $null }
    }
    if ($ollama) {
        $up = $false
        for ($i = 0; $i -lt 30 -and -not $up; $i++) {
            try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true }
            catch { if ($i -eq 0) { Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden }; Start-Sleep 2 }
        }
        if (-not $up) { Warn "Ollama isn't answering; skipping the model download. Ideas are used as written." }
        else {
            Info "Downloading $LlmModel (about 8 GB)..."
            & $ollama pull $LlmModel
            if ($LASTEXITCODE -ne 0) { Warn "Couldn't download $LlmModel; ideas are used as written." }
            else { $settings["ollama_model"] = $LlmModel }
        }
    }
}

$settings | ConvertTo-Json | Set-Content -Encoding utf8 $settingsFile

# ---------------------------------------------------------------- 6. the AI models
Step 6 "AI models (about 35 GB the first time)"
if ($SkipModels) {
    Info "Skipped. Each model downloads the first time it's needed."
} else {
    Info "Each 3D step runs once on a test picture; it downloads its model first if needed."
    & $AppPy (Join-Path $PSScriptRoot "prefetch.py")
    if ($LASTEXITCODE -ne 0) { Fail "A model couldn't be downloaded or didn't run on this graphics card." }
}

# ---------------------------------------------------------------- 7. shortcuts
Step 7 "Shortcuts"
$pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Print Studio.lnk"
$links = @((Join-Path ([Environment]::GetFolderPath("Desktop")) "Print Studio.lnk"), $startMenu)
if ($NoShortcuts) { $links = @(); Info "Skipped (-NoShortcuts)." }
foreach ($lnk in $links) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $pythonw
    $s.Arguments = "`"$(Join-Path $Root 'app\main.py')`""
    $s.WorkingDirectory = Join-Path $Root "app"
    $s.IconLocation = (Join-Path $Root "app\static\icon.ico") + ",0"
    $s.Description = "Print Studio: ideas, photos and 3D files to multicolour prints"
    $s.Save()
}
Info "Desktop and Start-menu shortcuts made."

Set-Content -Path (Join-Path $Root ".installed") -Value (Get-Date -Format s)
Write-Host ""
Write-Host "  Print Studio is installed. Open it from the desktop icon." -ForegroundColor Green
Stop-Transcript | Out-Null
if (-not $FromSetupExe) {
    $a = Read-Host "Open Print Studio now? [Y/n]"
    if ($a -notmatch "^[nN]") { Start-Process $pythonw -ArgumentList "`"$(Join-Path $Root 'app\main.py')`"" -WorkingDirectory (Join-Path $Root "app") }
}
exit 0
