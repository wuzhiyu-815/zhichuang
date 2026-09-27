param(
    [ValidateSet('run', 'check', 'update', 'push', 'python')]
    [string]$Action = 'run',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)
$ErrorActionPreference = 'Stop'
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $root = Split-Path -Parent $PSScriptRoot
    Set-Location -LiteralPath $root
    $bundle = Join-Path $root 'vendor\windows-x64'
    $manifestPath = Join-Path $bundle 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $version = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLower().Substring(0, 16)
    $runtime = $root
    $python = Join-Path $runtime 'python\python.exe'
    $ffmpeg = Join-Path $runtime 'ffmpeg\ffmpeg.exe'
    $ffprobe = Join-Path $runtime 'ffmpeg\ffprobe.exe'
    $ready = Join-Path $root 'python\.bundle-version'
    $installedVersion = ''
    if (Test-Path -LiteralPath $ready) { $installedVersion = (Get-Content -LiteralPath $ready -Raw).Trim() }
    if (-not (($installedVersion -eq $version) -and (Test-Path -LiteralPath $python) -and
              (Test-Path -LiteralPath $ffmpeg) -and (Test-Path -LiteralPath $ffprobe))) {
        Write-Host 'Preparing python and ffmpeg folders in the project directory...'
        $running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.ExecutablePath -and ((Split-Path -Parent $_.ExecutablePath) -eq (Split-Path -Parent $python)) }
        if ($running) { throw 'Close this project application before updating its bundled runtime.' }
        # Verify every archive before overwriting an existing runtime.
        foreach ($package in $manifest.packages) {
            if ($package.file -notmatch '^[a-z0-9-]+\.zip$') { throw 'Invalid runtime package name.' }
            $archive = Join-Path $bundle $package.file
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $package.sha256) {
                throw "Runtime checksum mismatch: $($package.file). Download the repository again."
            }
        }
        foreach ($package in $manifest.packages) {
            Expand-Archive -LiteralPath (Join-Path $bundle $package.file) -DestinationPath $runtime -Force
        }
        if (-not ((Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath $ffmpeg) -and
                  (Test-Path -LiteralPath $ffprobe))) { throw 'Incomplete Windows runtime.' }
        Set-Content -LiteralPath $ready -Value $version -Encoding ASCII
        Set-Content -LiteralPath (Join-Path $root 'python\.requirements-sha256') -Value $manifest.requirements_sha256 -Encoding ASCII
    }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PATH = "$(Join-Path $runtime 'ffmpeg');$(Split-Path -Parent $python);$env:PATH"
    if (-not $env:SHORT_DRAMA_MULTIUSER) { $env:SHORT_DRAMA_MULTIUSER = '0' }
    if (-not $env:SHORT_DRAMA_PORT) { $env:SHORT_DRAMA_PORT = '7860' }

    if ($Action -eq 'run') {
        $requirementsText = [IO.File]::ReadAllText((Join-Path $root 'requirements.txt')).Replace("`r`n", "`n")
        $hasher = [Security.Cryptography.SHA256]::Create()
        $requirements = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($requirementsText)))).Replace('-', '')
        $hasher.Dispose()
        $installedPath = Join-Path $root 'python\.requirements-sha256'
        $installed = $manifest.requirements_sha256
        if (Test-Path -LiteralPath $installedPath) { $installed = (Get-Content -LiteralPath $installedPath -Raw).Trim() }
        if ($requirements -ne $installed) {
            & $python -m pip install --upgrade --target (Join-Path $runtime 'python\Lib\site-packages') -r requirements.txt
            if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
            Set-Content -LiteralPath $installedPath -Value $requirements -Encoding ASCII
        }
        if (-not (Test-Path -LiteralPath (Join-Path $root 'config.json'))) {
            Copy-Item -LiteralPath (Join-Path $root 'config.example.json') -Destination (Join-Path $root 'config.json')
        }
        Write-Host "Zhichuang - http://127.0.0.1:$env:SHORT_DRAMA_PORT"
        & $python -u (Join-Path $root 'app.py') @AppArgs
    } elseif ($Action -eq 'check') {
        & $python -c "import sys, ssl, sqlite3, flask, requests, waitress, websocket, pyJianYingDraft; print(sys.version); print('Bundled dependencies: OK')"
        if ($LASTEXITCODE -ne 0) { throw 'Python runtime check failed.' }
        & $ffmpeg -version
        if ($LASTEXITCODE -ne 0) { throw 'FFmpeg check failed.' }
        & $ffprobe -version
    } elseif ($Action -eq 'python') {
        & $python @AppArgs
    } else {
        & $python -m infrastructure.system_update $Action @AppArgs
    }
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
