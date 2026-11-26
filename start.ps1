param([int]$Port = 18765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$pythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonExe)) {
    Write-Host 'First run: preparing Python environment...'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
    & $pythonExe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network and retry.' }
}
if (!(Test-Path -LiteralPath 'frontend/dist/index.html')) {
    Push-Location -LiteralPath 'frontend'
    try {
        pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        node node_modules/typescript/bin/tsc -b
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript validation failed.' }
        node node_modules/vite/bin/vite.js build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
$baseUrl = 'http://127.0.0.1:' + $Port
try {
    $existing = Invoke-RestMethod -Uri ($baseUrl + '/api/health') -TimeoutSec 2
    if ($existing.app_id -eq 'delivery-workbench') {
        if (!$NoBrowser) { Start-Process $baseUrl }
        Write-Host ('Already running: ' + $baseUrl)
        exit 0
    }
} catch { }
Write-Host ('Delivery Workbench: ' + $baseUrl)
Write-Host 'Keep this window open. Press Ctrl+C to stop safely.'
$runArgs = @('scripts/run.py', '--port', [string]$Port)
if ($NoBrowser) { $runArgs += '--no-browser' }
& $pythonExe @runArgs
if ($LASTEXITCODE -ne 0) { throw 'Service could not start. The port may be in use; try: ./start.ps1 -Port 18766' }
