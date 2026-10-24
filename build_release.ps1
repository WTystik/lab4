$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install requirements-dev.txt first.' }
& $taskPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $taskPython -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
if ($LASTEXITCODE -ne 0) { throw 'Wheel build failed.' }
$taskRelease = Join-Path $PSScriptRoot 'release\jira-lab4-analytics'
New-Item -ItemType Directory -Path $taskRelease -Force | Out-Null
$taskWheel = Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'dist') -Filter 'jira_lab4_analytics-1.0.0-*.whl' | Select-Object -First 1
if (-not $taskWheel) { throw 'Built wheel not found.' }
Copy-Item -LiteralPath $taskWheel.FullName -Destination $taskRelease
foreach ($taskFile in @('config.toml', 'start.cmd', 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $taskFile) -Destination $taskRelease
}
Compress-Archive -LiteralPath $taskRelease -DestinationPath (Join-Path $PSScriptRoot 'dist\jira-lab4-analytics-windows.zip') -Force
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'dist') | Select-Object Name,Length
