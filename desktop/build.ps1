# Builds the TraceWorks Windows installer.
#
#   powershell -ExecutionPolicy Bypass -File desktop\build.ps1 [-Version 0.1.0]
#
# Output: desktop\dist\TraceWorks\TraceWorks.exe (the app folder) and, when
# Inno Setup 6 is installed, desktop\dist\TraceWorks-Setup-<version>.exe.
param([string]$Version = "0.1.0")

$ErrorActionPreference = "Stop"
$Desktop = $PSScriptRoot
$Root = Split-Path $Desktop -Parent

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed ($LASTEXITCODE)" } }

# 1. The UI, as a static export for the desktop.
Step "Building the UI (static export)"
Push-Location "$Root\userpage"
try {
    if (-not (Test-Path node_modules)) { npm ci; Check "npm ci" }
    $env:NEXT_PUBLIC_DESKTOP = "1"
    npx next build; Check "next build"
} finally {
    Remove-Item Env:NEXT_PUBLIC_DESKTOP -ErrorAction SilentlyContinue
    Pop-Location
}

# 2. A clean Python environment, so only what the app needs is bundled.
Step "Preparing the Python environment"
$Py = "$Desktop\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { python -m venv "$Desktop\.venv"; Check "venv" }
& $Py -m pip install --quiet --upgrade pip; Check "pip upgrade"
& $Py -m pip install --quiet -r "$Desktop\requirements.txt"; Check "pip install"

# 3. The app folder.
Step "Bundling with PyInstaller"
Push-Location $Desktop
try {
    & $Py -m PyInstaller traceworks.spec --noconfirm --clean `
        --distpath dist --workpath build; Check "PyInstaller"
} finally { Pop-Location }

# 4. The installer.
Step "Building the installer"
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    Write-Warning ("Inno Setup 6 not found; skipped the installer. The app " +
        "itself is in desktop\dist\TraceWorks. Install it with: " +
        "winget install JRSoftware.InnoSetup")
    exit 0
}
& $Iscc "/DAppVersion=$Version" "$Desktop\installer.iss"; Check "ISCC"
Write-Host "`nDone: desktop\dist\TraceWorks-Setup-$Version.exe" -ForegroundColor Green
