$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyinstallerPath = Join-Path $projectRoot '.venv\Scripts\pyinstaller.exe'
$entryPath = Join-Path $projectRoot 'main.py'
$iconPath = Join-Path $projectRoot 'app.ico'
$outputPath = Join-Path $projectRoot 'dist'
$buildPath = Join-Path $projectRoot 'build'

$pyinstallerCommand = $pyinstallerPath
if (-not (Test-Path -LiteralPath $pyinstallerPath)) {
    $installed = Get-Command pyinstaller.exe -ErrorAction SilentlyContinue
    if ($null -eq $installed) {
        throw 'PyInstaller is missing. Install requirements-dev.txt before building.'
    }
    $pyinstallerCommand = $installed.Source
}

if (-not (Test-Path -LiteralPath $iconPath)) {
    throw 'Application icon is missing. Run make_icon.py before building.'
}

& $pyinstallerCommand `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --uac-admin `
    --icon $iconPath `
    --add-data "$iconPath;." `
    --name '连点器' `
    --distpath $outputPath `
    --workpath $buildPath `
    --specpath $projectRoot `
    $entryPath
