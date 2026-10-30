# Offline installer for Project Atlas on Windows 10/11 (PowerShell). Requires Python 3.11+ (python.org installer).
# The wheelhouse must have been built on Windows (scripts/build_release.sh equivalent): wheels are platform specific.
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Dest "$env:LOCALAPPDATA\Project Atlas"]
param([string]$Dest = "$env:LOCALAPPDATA\Project Atlas")
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" } else { $py = "python" }
& $py -c "import sys; assert sys.version_info >= (3, 11)"
if (Test-Path "$Here\SHA256SUMS") {
  Get-Content "$Here\SHA256SUMS" | ForEach-Object {
    $hash, $file = $_ -split "  ", 2
    $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $Here $file.TrimStart(".", "/"))).Hash.ToLower()
    if ($actual -ne $hash) { throw "Checksum mismatch: $file" }
  }
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
& $py -m venv "$Dest\venv"
& "$Dest\venv\Scripts\python.exe" -m pip install --no-index --find-links "$Here\wheelhouse" project-atlas
if (-not (Test-Path "$Dest\.env")) {
  (Get-Content "$Here\.env.example") -replace '^ATLAS_STORAGE_DIR=.*', "ATLAS_STORAGE_DIR=$Dest\atlas-workspace" `
    -replace '^ATLAS_BACKUP_DIR=.*', "ATLAS_BACKUP_DIR=$Dest\atlas-backups" -replace '^ATLAS_MODEL_DIR=.*', "ATLAS_MODEL_DIR=$Dest\models" |
    Set-Content "$Dest\.env"
}
@"
@echo off
cd /d "$Dest"
"$Dest\venv\Scripts\atlas.exe" %*
"@ | Set-Content "$Dest\atlas.cmd"
Write-Host "Installed. Run: `"$Dest\atlas.cmd`" offline-check   then   `"$Dest\atlas.cmd`" serve"
