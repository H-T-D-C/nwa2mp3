param(
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) {
    $Python = Join-Path $repoRoot '.venv\Scripts\python.exe'
} elseif (-not [System.IO.Path]::IsPathRooted($Python)) {
    $Python = Join-Path $repoRoot $Python
}
$pythonExe = (Resolve-Path $Python).Path
$specFile = Join-Path $repoRoot 'packaging\Nwa2Mp3.spec'
$distRoot = Join-Path $repoRoot 'dist'
$workRoot = Join-Path $repoRoot 'build\release-work'
$appDirectory = Join-Path $distRoot 'Nwa2Mp3'
$archivePath = Join-Path $distRoot 'Nwa2Mp3-Windows-x64.zip'

Push-Location $repoRoot
try {
    Write-Output "Using Python: $pythonExe"
    & $pythonExe --version
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not start (exit code $LASTEXITCODE)."
    }
    & $pythonExe -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot $specFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $appDirectory 'Nwa2Mp3.exe'))) {
        throw 'The packaged Nwa2Mp3.exe was not created.'
    }
    Copy-Item -LiteralPath (Join-Path $repoRoot 'README.md') -Destination $appDirectory -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'THIRD_PARTY_NOTICES.md') -Destination $appDirectory -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination $appDirectory -Force
    $docsDirectory = Join-Path $appDirectory 'docs'
    New-Item -ItemType Directory -Path $docsDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\SETUP.md') -Destination $docsDirectory -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'docs\DEVELOPMENT.md') -Destination $docsDirectory -Force
    $licenseDirectory = Join-Path $appDirectory 'LICENSES'
    New-Item -ItemType Directory -Path $licenseDirectory -Force | Out-Null
    Copy-Item -Path (Join-Path $repoRoot 'LICENSES\*') -Destination $licenseDirectory -Force
    Compress-Archive -Path (Join-Path $appDirectory '*') -DestinationPath $archivePath -Force
    Write-Output "Created $archivePath"
}
finally {
    Pop-Location
}
