param([string]$InstallDirectory)
$ErrorActionPreference = 'Stop'
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
if (Test-Path -LiteralPath (Join-Path $packageRoot 'source\services\deploy\deploy.py')) {
    $sourceRoot = Join-Path $packageRoot 'source'
    $pythonExecutable = Join-Path $packageRoot 'runtime\python.exe'
} else {
    $sourceRoot = Split-Path -Parent $packageRoot
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $pythonExecutable = if ($pythonCommand) { $pythonCommand.Source } else { $null }
}
if (-not $pythonExecutable -or -not (Test-Path -LiteralPath $pythonExecutable)) {
    throw '此源码入口需要 Python 3.10+；新机器请下载包含独立 Python 的 Orca Deploy Windows 安装包。'
}
$scriptFile = Join-Path $sourceRoot 'services\deploy\deploy.py'
if (-not (Test-Path -LiteralPath $scriptFile)) { throw 'Deployment source is missing.' }
# A packaged distribution verifies its exact files before starting. This is an
# integrity check; the trusted download/release remains the authenticity anchor.
$manifestFile = Join-Path $packageRoot 'package-manifest.json'
if (Test-Path -LiteralPath $manifestFile) {
    $manifest = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
    foreach ($item in $manifest.files) {
        $resolvedFile = [IO.Path]::GetFullPath((Join-Path $packageRoot $item.path))
        if (-not $resolvedFile.StartsWith($packageRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid package path.' }
        if ((Get-FileHash -LiteralPath $resolvedFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw 'Deployment package integrity check failed.' }
    }
}
$launcherDirectory = Join-Path $env:LOCALAPPDATA 'OrcaDeploy'
New-Item -ItemType Directory -Path $launcherDirectory -Force | Out-Null
@{python=$pythonExecutable;source=$sourceRoot} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $launcherDirectory 'launcher.json') -Encoding UTF8
# Reuse the unified entry if it already contains the deployment module.
try {
    $existing = Invoke-WebRequest -Uri 'http://127.0.0.1:18774/' -UseBasicParsing -TimeoutSec 2
    if ($existing.StatusCode -eq 200 -and $existing.Content.Contains('data-view="deploy"')) {
        Start-Process 'http://127.0.0.1:18774/#deploy' -WindowStyle Hidden
        exit 0
    }
} catch { }
# Execution stays independent of Orca/Codex. No root password or token is passed
# on this command line; those are entered later into the local-only UI.
Start-Process -FilePath $pythonExecutable -ArgumentList @('"'+$scriptFile+'"','serve','--open') -WindowStyle Hidden
