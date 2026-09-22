[CmdletBinding()]
param(
    [switch]$ResetDemoData
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Executable,
        [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$CommandArguments
    )
    & $Executable @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Befehl fehlgeschlagen ($LASTEXITCODE): $Executable $($CommandArguments -join ' ')"
    }
}

function Get-SystemPython {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $LauncherUsable = $false
        try {
            & $launcher.Source -3 -c "import sys; raise SystemExit(sys.version_info < (3, 12))" 2>$null
            $LauncherUsable = $LASTEXITCODE -eq 0
        } catch {
            $LauncherUsable = $false
        }
        if ($LauncherUsable) {
            return [PSCustomObject]@{ Executable = $launcher.Source; Prefix = @("-3") }
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $PythonUsable = $false
        try {
            & $python.Source -c "import sys; raise SystemExit(sys.version_info < (3, 12))" 2>$null
            $PythonUsable = $LASTEXITCODE -eq 0
        } catch {
            $PythonUsable = $false
        }
        if ($PythonUsable) {
            return [PSCustomObject]@{ Executable = $python.Source; Prefix = @() }
        }
    }
    throw "Python 3.12 oder neuer wurde nicht gefunden. Python installieren und das Setup erneut starten."
}

Push-Location $ProjectRoot
try {
    $SystemPython = Get-SystemPython
    $PythonExecutable = $SystemPython.Executable
    $PythonPrefix = @($SystemPython.Prefix)

    & $PythonExecutable @PythonPrefix "scripts/check_environment.py" --mode setup
    if ($LASTEXITCODE -ne 0) {
        throw "Die Systemvoraussetzungen sind nicht erfüllt."
    }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host "Virtuelle Umgebung .venv wird erstellt ..."
        & $PythonExecutable @PythonPrefix -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Die virtuelle Umgebung konnte nicht erstellt werden."
        }
    }

    Invoke-Checked $VenvPython -m pip install --disable-pip-version-check -r requirements.txt

    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $ProjectRoot ".env")
        Write-Host ".env wurde aus .env.example erzeugt."
    } else {
        Write-Host "Vorhandene .env bleibt unverändert."
    }

    $RuntimeDatabase = Join-Path $ProjectRoot "data\masterdata.db"
    if ($ResetDemoData -or -not (Test-Path -LiteralPath $RuntimeDatabase)) {
        Invoke-Checked $VenvPython -m data.generate
    } else {
        Write-Host "Vorhandene Demodaten bleiben unverändert. Für einen Reset -ResetDemoData verwenden."
    }

    & $VenvPython scripts/check_environment.py --mode runtime
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Die Projektinstallation ist abgeschlossen, aber Ollama oder ein Modell fehlt noch."
        exit 1
    }
    Invoke-Checked $VenvPython demo.py --check

    Write-Host ""
    Write-Host "Installation abgeschlossen. Start:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts/start.ps1"
}
finally {
    Pop-Location
}
