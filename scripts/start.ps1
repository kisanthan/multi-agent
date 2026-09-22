[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectRoot ".runtime_logs"
$StartedProcesses = @()

function Test-PortOpen {
    param([int]$Port)
    $Client = [System.Net.Sockets.TcpClient]::new()
    try {
        $Client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $Client.Dispose()
    }
}

function Test-MockHealth {
    param([string]$Url, [string]$ExpectedSystem)
    try {
        $Response = Invoke-RestMethod -Uri $Url -TimeoutSec 1
        return $Response.status -eq "ok" -and $Response.system -eq $ExpectedSystem
    } catch {
        return $false
    }
}

function Test-Streamlit {
    try {
        $Response = Invoke-WebRequest -Uri "http://127.0.0.1:8501" -UseBasicParsing -TimeoutSec 1
        return $Response.StatusCode -eq 200 -and $Response.Content -match "Streamlit"
    } catch {
        return $false
    }
}

function Wait-ForHealth {
    param([string]$Url, [string]$ExpectedSystem, [System.Diagnostics.Process]$Process)
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if ($Process.HasExited) {
            throw "Dienst wurde vor der Bereitschaft beendet: $Url"
        }
        try {
            if (Test-MockHealth $Url $ExpectedSystem) { return }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Dienst wurde nicht rechtzeitig bereit: $Url"
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $Python)) {
        throw ".venv fehlt. Zuerst scripts/setup.ps1 ausführen."
    }
    & $Python scripts/check_environment.py --mode start
    if ($LASTEXITCODE -ne 0) {
        throw "Die Startvoraussetzungen sind nicht erfüllt."
    }

    $NavisionReady = Test-MockHealth "http://127.0.0.1:8001/health" "navision-mock"
    $EloReady = Test-MockHealth "http://127.0.0.1:8002/health" "elo-mock"
    $StreamlitReady = Test-Streamlit
    if ((Test-PortOpen 8001) -and -not $NavisionReady) {
        throw "Port 8001 ist durch einen anderen Dienst belegt."
    }
    if ((Test-PortOpen 8002) -and -not $EloReady) {
        throw "Port 8002 ist durch einen anderen Dienst belegt."
    }
    if ((Test-PortOpen 8501) -and -not $StreamlitReady) {
        throw "Port 8501 ist durch einen anderen Dienst belegt."
    }
    if ($NavisionReady -and $EloReady -and $StreamlitReady) {
        Write-Host "Der Prototyp läuft bereits unter http://127.0.0.1:8501."
        return
    }

    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    if (-not $NavisionReady) {
        $Navision = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "mocks.navision:app", "--port", "8001") -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogDirectory "navision-$Stamp.out.log") -RedirectStandardError (Join-Path $LogDirectory "navision-$Stamp.err.log") -WindowStyle Hidden -PassThru
        $StartedProcesses += $Navision
        Wait-ForHealth "http://127.0.0.1:8001/health" "navision-mock" $Navision
    } else {
        Write-Host "Vorhandener Navision-Mock wird wiederverwendet."
    }
    if (-not $EloReady) {
        $Elo = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "mocks.elo:app", "--port", "8002") -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogDirectory "elo-$Stamp.out.log") -RedirectStandardError (Join-Path $LogDirectory "elo-$Stamp.err.log") -WindowStyle Hidden -PassThru
        $StartedProcesses += $Elo
        Wait-ForHealth "http://127.0.0.1:8002/health" "elo-mock" $Elo
    } else {
        Write-Host "Vorhandener ELO-Mock wird wiederverwendet."
    }
    Write-Host "Mocks sind bereit. Streamlit startet; Beenden mit Ctrl+C."
    & $Python -m streamlit run ui/app.py --server.port 8501
}
finally {
    foreach ($Process in $StartedProcesses) {
        if ($Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Pop-Location
}
