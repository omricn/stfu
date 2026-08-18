<#
.SYNOPSIS
    Builds dist\stfu.exe with PyInstaller.

.DESCRIPTION
    Cleans dist\ and build\, runs PyInstaller against stfu.spec, and prints
    the resulting exe's path and size. Run from the repo root, or anywhere --
    it locates itself.
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Cleaning dist\ and build\ ..."
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue

$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    throw "PyInstaller not found at $pyinstaller -- install the dev extras first."
}

Write-Host "Running PyInstaller..."
& $pyinstaller "stfu.spec" --noconfirm
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$exePath = Join-Path $root "dist\stfu.exe"
if (-not (Test-Path $exePath)) {
    throw "Build finished but $exePath was not found"
}

$sizeMb = [Math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host ""
Write-Host "Built: $exePath ($sizeMb MB)"
