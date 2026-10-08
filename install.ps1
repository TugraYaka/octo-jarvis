# Installs JARVIS: downloads the latest release and adds the 'jarvis' command.
#   irm https://raw.githubusercontent.com/TugraYaka/octo-jarvis/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = "TugraYaka/octo-jarvis"
if (-not [Environment]::Is64BitOperatingSystem) { throw "JARVIS needs 64-bit Windows." }

$data = if ($env:JARVIS_HOME) { $env:JARVIS_HOME } else { Join-Path $env:LOCALAPPDATA "JARVIS" }
$name = "jarvis-windows-x64.zip"
$base = if ($env:JARVIS_BASE_URL) { $env:JARVIS_BASE_URL } elseif ($env:JARVIS_VERSION) { "https://github.com/$repo/releases/download/$($env:JARVIS_VERSION)" } else { "https://github.com/$repo/releases/latest/download" }

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("jarvis-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading $name ..."
    Invoke-WebRequest -Uri "$base/$name" -OutFile (Join-Path $tmp $name)
    Invoke-WebRequest -Uri "$base/$name.sha256" -OutFile (Join-Path $tmp "$name.sha256")

    $expected = ((Get-Content (Join-Path $tmp "$name.sha256") -Raw).Trim() -split "\s+")[0]
    $actual = (Get-FileHash (Join-Path $tmp $name) -Algorithm SHA256).Hash
    if ($expected -ne $actual) { throw "Checksum mismatch, aborting." }

    New-Item -ItemType Directory -Force -Path $data | Out-Null
    $staging = Join-Path $data "app.new"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    Expand-Archive -Path (Join-Path $tmp $name) -DestinationPath $staging
    $app = Join-Path $data "app"
    if (Test-Path $app) { Remove-Item -Recurse -Force $app }
    Move-Item (Join-Path $staging "jarvis") $app
    Remove-Item -Recurse -Force $staging

    & (Join-Path $app "jarvis.exe") install
    Write-Host ""
    Write-Host "JARVIS installed. Open a new terminal and run 'jarvis setup' for the guided setup, or just 'jarvis'."
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
