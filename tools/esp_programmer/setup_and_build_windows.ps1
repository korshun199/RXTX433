$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=========================================="
Write-Host " ESP Programmer - setup and Windows build"
Write-Host "=========================================="
Write-Host ""

function Test-PythonCandidate {
    param([string]$Exe)

    if (-not $Exe -or -not (Test-Path $Exe)) {
        return $null
    }

    try {
        $result = & $Exe -c "import sys, struct; print(sys.version_info.major, sys.version_info.minor, struct.calcsize('P')*8, sys.executable)" 2>$null
        if (-not $result) {
            return $null
        }

        $parts = $result.Trim().Split(" ", 4)
        if ($parts.Count -lt 4) {
            return $null
        }

        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        $bits  = [int]$parts[2]
        $path  = $parts[3]

        if ($major -eq 3 -and $minor -ge 10 -and $minor -lt 15 -and $bits -eq 64) {
            return $path
        }
    }
    catch {
        return $null
    }

    return $null
}

Write-Host "[1/7] Searching for a usable 64-bit Python..."

$candidates = New-Object System.Collections.Generic.List[string]

$cmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($cmd) {
    $candidates.Add($cmd.Source)
}

$cmd3 = Get-Command python3.exe -ErrorAction SilentlyContinue
if ($cmd3) {
    $candidates.Add($cmd3.Source)
}

$roots = @(
    "$env:LOCALAPPDATA\Programs\Python",
    "$env:ProgramFiles",
    "${env:ProgramFiles(x86)}"
) | Where-Object { $_ -and (Test-Path $_) }

foreach ($root in $roots) {
    Get-ChildItem -Path $root -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add($_.FullName) }
}

$registryPaths = @(
    "HKCU:\Software\Python\PythonCore",
    "HKLM:\Software\Python\PythonCore",
    "HKLM:\Software\WOW6432Node\Python\PythonCore"
)

foreach ($regPath in $registryPaths) {
    if (Test-Path $regPath) {
        Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
            $installPathKey = Join-Path $_.PSPath "InstallPath"
            try {
                $installDir = (Get-ItemProperty $installPathKey -ErrorAction Stop)."(default)"
                if (-not $installDir) {
                    $installDir = (Get-ItemProperty $installPathKey -ErrorAction Stop).ExecutablePath
                }
                if ($installDir) {
                    if (Test-Path $installDir -PathType Leaf) {
                        $candidates.Add($installDir)
                    } else {
                        $candidates.Add((Join-Path $installDir "python.exe"))
                    }
                }
            } catch {}
        }
    }
}

$PythonExe = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    $valid = Test-PythonCandidate $candidate
    if ($valid) {
        $PythonExe = $valid
        break
    }
}

if (-not $PythonExe) {
    Write-Host ""
    Write-Host "ERROR: A suitable 64-bit Python was not found."
    Write-Host "Install Python 3.13 x64 and then run this script again."
    Write-Host "During installation enable: Add python.exe to PATH"
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Found Python:"
Write-Host "  $PythonExe"
& $PythonExe -c "import sys, platform; print('  Version:', sys.version); print('  Architecture:', platform.architecture())"

Write-Host ""
Write-Host "[2/7] Recreating virtual environment..."

if (Test-Path ".\venv") {
    Remove-Item -Recurse -Force ".\venv"
}

& $PythonExe -m venv ".\venv"

$VenvPython = (Resolve-Path ".\venv\Scripts\python.exe").Path

Write-Host ""
Write-Host "[3/7] Installing dependencies..."

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install PySide6 pyserial esptool pyinstaller

Write-Host ""
Write-Host "[4/7] Checking dependencies..."

& $VenvPython -c "import PySide6, serial, esptool, PyInstaller; print('PySide6:', PySide6.__version__)"

if (-not (Test-Path ".\esp_programmer.py")) {
    throw "esp_programmer.py was not found next to this script."
}

Write-Host ""
Write-Host "[5/7] Creating esptool launcher..."

@'
import runpy

if __name__ == "__main__":
    runpy.run_module("esptool", run_name="__main__")
'@ | Set-Content ".\esptool_launcher.py" -Encoding UTF8

Write-Host ""
Write-Host "[6/7] Cleaning old build..."

Remove-Item -Recurse -Force ".\build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force ".\dist" -ErrorAction SilentlyContinue
Remove-Item -Force ".\ESP_Programmer.spec" -ErrorAction SilentlyContinue
Remove-Item -Force ".\esptool.spec" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[7/7] Building ESP Programmer..."

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name ESP_Programmer `
    --collect-all PySide6 `
    --hidden-import serial.tools.list_ports `
    ".\esp_programmer.py"

if ($LASTEXITCODE -ne 0) {
    throw "ESP_Programmer build failed."
}

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name esptool `
    --collect-all esptool `
    --distpath ".\dist\ESP_Programmer" `
    ".\esptool_launcher.py"

if ($LASTEXITCODE -ne 0) {
    throw "esptool build failed."
}

$App = (Resolve-Path ".\dist\ESP_Programmer\ESP_Programmer.exe").Path
$Tool = (Resolve-Path ".\dist\ESP_Programmer\esptool.exe").Path

Write-Host ""
Write-Host "=========================================="
Write-Host " BUILD COMPLETED SUCCESSFULLY"
Write-Host "=========================================="
Write-Host ""
Write-Host "Application:"
Write-Host "  $App"
Write-Host ""
Write-Host "esptool:"
Write-Host "  $Tool"
Write-Host ""
Write-Host "Copy the whole folder:"
Write-Host "  $PSScriptRoot\dist\ESP_Programmer"
Write-Host ""

Start-Process $App
Read-Host "Press Enter to close this window"
