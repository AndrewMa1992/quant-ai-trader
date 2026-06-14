# Quant AI Trader - Watchdog Process
# Monitors all 3 components, auto-restarts if killed
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File watchdog.ps1

$ErrorActionPreference = "Continue"
$PROJECT_ROOT = "G:\workbuddyspace\Claw\quant-ai-trader"
$LOG_FILE = "$PROJECT_ROOT\logs\watchdog.log"
$CHECK_INTERVAL = 10

# Absolute paths (Registry Run doesn't have full PATH)
$PYTHON = "C:\Python314\python.exe"
$NPM = "C:\Program Files\nodejs\npm.cmd"
if (-not (Test-Path $PYTHON)) { $PYTHON = "python" }
if (-not (Test-Path $NPM)) { $NPM = "npm" }

$env:TORCH_HOME = "$PROJECT_ROOT\cache\torch"
$env:HF_HOME = "$PROJECT_ROOT\cache\huggingface"

New-Item -ItemType Directory -Force -Path "$PROJECT_ROOT\logs" | Out-Null

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts | $Message"
    Add-Content -Path $LOG_FILE -Value $line
    Write-Host $line
}

function Test-Port {
    param([int]$Port)
    try {
        $conn = New-Object System.Net.Sockets.TcpClient
        $result = $conn.BeginConnect("127.0.0.1", $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(3000)
        $conn.Close()
        return $success
    } catch {
        return $false
    }
}

function Invoke-GitPull {
    Write-Log "[GIT] Pulling latest code..."
    try {
        $prevDir = Get-Location
        Set-Location $PROJECT_ROOT
        # Git may not be on PATH, try common locations
        $gitPath = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
        if (-not $gitPath) {
            if (Test-Path "C:\Program Files\Git\bin\git.exe") { $gitPath = "C:\Program Files\Git\bin\git.exe" }
            elseif (Test-Path "C:\Program Files (x86)\Git\bin\git.exe") { $gitPath = "C:\Program Files (x86)\Git\bin\git.exe" }
            else { Write-Log "[GIT] git not found, skipping pull"; return }
        }
        $output = & $gitPath pull origin main 2>&1 | Out-String
        Set-Location $prevDir
        if ($output -match "Already up to date") {
            Write-Log "[GIT] Already up to date"
        } elseif ($output -match "fatal|cannot connect|error") {
            Write-Log "[GIT] WARN: Pull failed - $($output.Trim())"
        } else {
            $short = ($output -split "`n")[0]
            Write-Log "[GIT] Updated: $short"
        }
    } catch {
        Write-Log "[GIT] ERROR: $_"
    }
}

# ================================================================
# Component Management
# ================================================================

function Start-Backend {
    if (Test-Port 8001) {
        Write-Log "[Backend] Already running on port 8001"
        return $true
    }
    Write-Log "[Backend] Starting..."
    try {
        $proc = Start-Process -FilePath $PYTHON `
            -ArgumentList "run_backend.py" `
            -WorkingDirectory $PROJECT_ROOT `
            -WindowStyle Minimized `
            -PassThru
        Write-Log "[Backend] Started (PID: $($proc.Id))"
        
        for ($i = 0; $i -lt 35; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Port 8001) {
                Write-Log "[Backend] OK - ready"
                return $true
            }
        }
        Write-Log "[Backend] FAIL: startup timeout"
        return $false
    } catch {
        Write-Log "[Backend] FAIL: $_"
        return $false
    }
}

function Start-Frontend {
    if (Test-Port 5180) {
        Write-Log "[Frontend] Already running on port 5180"
        return $true
    }
    Write-Log "[Frontend] Starting..."
    try {
        $proc = Start-Process -FilePath "cmd" `
            -ArgumentList "/c `"$NPM` run dev`" `
            -WorkingDirectory "$PROJECT_ROOT\frontend" `
            -WindowStyle Minimized `
            -PassThru
        Write-Log "[Frontend] Started (PID: $($proc.Id))"
        
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Port 5180) {
                Write-Log "[Frontend] OK - ready"
                return $true
            }
        }
        Write-Log "[Frontend] FAIL: startup timeout"
        return $false
    } catch {
        Write-Log "[Frontend] FAIL: $_"
        return $false
    }
}

function Start-AutoTrader {
    # Check if already running
    $existing = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
        try { ($_ | Get-WmiObject Win32_Process).CommandLine -match "auto_trader" } catch { $false }
    }
    if ($existing) {
        Write-Log "[Trader] Already running (PID: $($existing.Id))"
        return $true
    }
    Write-Log "[Trader] Starting (3min cycle)..."
    try {
        $proc = Start-Process -FilePath $PYTHON `
            -ArgumentList "auto_trader.py --interval 180" `
            -WorkingDirectory $PROJECT_ROOT `
            -WindowStyle Minimized `
            -PassThru
        Write-Log "[Trader] Started (PID: $($proc.Id))"
        return $true
    } catch {
        Write-Log "[Trader] FAIL: $_"
        return $false
    }
}

function Test-And-Restart-All {
    # Backend
    if (-not (Test-Port 8001)) {
        Write-Log "[Backend] DOWN - restarting..."
        Start-Backend | Out-Null
    }
    
    # Frontend
    if (-not (Test-Port 5180)) {
        Write-Log "[Frontend] DOWN - restarting..."
        Start-Frontend | Out-Null
    }
    
    # AutoTrader - check if log file is being updated (indicates alive)
    $logFiles = Get-ChildItem "$PROJECT_ROOT\logs\auto_trader_*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $traderAlive = $false
    if ($logFiles) {
        $age = (Get-Date) - $logFiles.LastWriteTime
        if ($age.TotalMinutes -lt 5) {
            $traderAlive = $true
        }
    }
    if (-not $traderAlive) {
        Write-Log "[Trader] DOWN - restarting..."
        Start-AutoTrader | Out-Null
    }
}

# ================================================================
# Main Loop
# ================================================================

Write-Log "============================================"
Write-Log "  Quant AI Trader Watchdog Started"
Write-Log "  Project: $PROJECT_ROOT"
Write-Log "  Check Interval: ${CHECK_INTERVAL}s"
Write-Log "============================================"

# 1. Pull latest code
Invoke-GitPull

# 2. Start all components
Write-Log "[Init] Starting all components..."
$backendOk = Start-Backend
if ($backendOk) { Start-Sleep -Seconds 5 }

$frontendOk = Start-Frontend
Start-Sleep -Seconds 2

$traderOk = Start-AutoTrader

Write-Log "[Status] Backend=$backendOk | Frontend=$frontendOk | Trader=$traderOk"

# 3. Continuous monitoring
$iteration = 0
while ($true) {
    $iteration++
    Start-Sleep -Seconds $CHECK_INTERVAL
    
    try {
        Test-And-Restart-All
        
        # Pull latest code every ~10 minutes
        if ($iteration % 60 -eq 0) {
            Invoke-GitPull
        }
    } catch {
        Write-Log "[Watchdog] Check error: $_"
    }
}
