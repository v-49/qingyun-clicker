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

# Only resolve DLLs from Windows and this Python environment. Developer PATH
# entries can contain incompatible ICU/UCRT DLLs from unrelated applications.
$originalBuildPath = $env:PATH
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python.exe -ErrorAction Stop).Source
}
$pythonBase = & $pythonPath -c 'import sys; print(sys.base_prefix)'
try {
    $env:PATH = @((Split-Path -Parent $pythonPath), $pythonBase, (Join-Path $pythonBase 'DLLs'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    & $pyinstallerCommand `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --uac-admin `
    --icon $iconPath `
    --add-data "$iconPath;." `
    --name '轻云连点器' `
    --distpath $outputPath `
    --workpath $buildPath `
    --specpath $projectRoot `
    $entryPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    & $pythonPath (Join-Path $projectRoot 'packaged_smoke.py') (Join-Path $outputPath '轻云连点器.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Packaged application failed its startup test.' }
}
finally {
    $env:PATH = $originalBuildPath
}
