param(
    [string]$InstallRoot = (Join-Path $PSScriptRoot "..\\tools\\poppler")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "oschwartz10612/poppler-windows"
$api = "https://api.github.com/repos/$repo/releases/latest"

$existingExe = Get-ChildItem -Path $InstallRoot -Recurse -Filter "pdftoppm.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingExe) {
    Write-Host "Poppler already installed at: $InstallRoot"
    exit 0
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

$headers = @{ "User-Agent" = "ASMEPurchaseOrderHelper" }
$release = Invoke-RestMethod -Uri $api -Headers $headers
$assets = @($release.assets)
$asset = $assets | Where-Object { $_.name -match "Release-.*\\.zip$" } | Select-Object -First 1
if (-not $asset -and $assets.Count -gt 0) {
    $asset = $assets | Select-Object -First 1
}
if (-not $asset) {
    throw "No Poppler Release ZIP asset found."
}

$zipPath = Join-Path $InstallRoot $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

Expand-Archive -Path $zipPath -DestinationPath $InstallRoot
Remove-Item -Path $zipPath -Force

Write-Host "Poppler installed under: $InstallRoot"
Write-Host "Add the bin folder (e.g., poppler-*/Library/bin) to PATH when using pdftoppm."
