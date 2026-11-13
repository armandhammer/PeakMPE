# Flash an image from scripts/build-image.sh on Windows, in one command:
# file check, dry run, then the real flash with a log. flash.py still asks
# for the confirmation (type flash); nothing is sent before that.
#
#   & "<repo>\scripts\flash.ps1" work\flash\<image>.syx
#
# Stops at the first step that fails. The log goes to
# work\flash-<sha8>-<date>.log, where the session reads it afterwards.
param([Parameter(Mandatory = $true)][string]$Image)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "no $py (docs/SETUP.md, hardware venv)" }
if (-not (Test-Path $Image)) { throw "no image $Image" }

$sha = (Get-FileHash -Algorithm SHA256 $Image).Hash.ToLower()
$log = "work\flash-$($sha.Substring(0, 8))-$(Get-Date -Format yyyy-MM-dd).log"
Write-Host "image  $Image"
Write-Host "sha256 $sha"

Write-Host "`n== 1/3 file check"
& $py -I tools\flash.py check $Image
if ($LASTEXITCODE -ne 0) { Write-Host "check failed: nothing sent"; exit $LASTEXITCODE }

Write-Host "`n== 2/3 dry run"
& $py -I tools\flash.py flash $Image --dry-run
if ($LASTEXITCODE -ne 0) { Write-Host "dry run failed: nothing sent"; exit $LASTEXITCODE }

Write-Host "`n== 3/3 flash (log $log)"
& $py -I tools\flash.py flash $Image --log $log
exit $LASTEXITCODE
