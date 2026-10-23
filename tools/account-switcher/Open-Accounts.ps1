param([Parameter(Mandatory=$true)][string]$Environment, [Parameter(Mandatory=$true)][string]$Worktree)
$ErrorActionPreference = 'Stop'
$orca = Join-Path $env:LOCALAPPDATA 'Programs\orca\resources\bin\orca.exe'

$panelUrl = 'http://127.0.0.1:18766/'

function Invoke-Orca([string[]]$Arguments) {
    $raw = & $orca @Arguments --environment $environment --json
    if ($LASTEXITCODE -ne 0) { throw "Orca command failed: $raw" }
    $response = $raw | ConvertFrom-Json
    if (-not $response.ok) { throw $response.error.message }
    if (-not $response._meta.runtimeId) { throw 'No remote runtime was returned. Check the the remote host connection.' }
    return $response.result
}

try {
    if (-not (Test-Path -LiteralPath $orca)) { throw 'Orca was not found. Install or open Orca first.' }
    $tabs = Invoke-Orca -Arguments @('tab','list')
    $existing = @($tabs.tabs | Where-Object { $_.url -eq $panelUrl }) | Select-Object -First 1
    if ($existing) {
        $null = Invoke-Orca -Arguments @('tab','switch','--page',$existing.browserPageId,'--focus')
    } else {
        $created = Invoke-Orca -Arguments @('tab','create','--worktree',$Worktree,'--url',$panelUrl)
        $null = Invoke-Orca -Arguments @('tab','switch','--page',$created.browserPageId,'--focus')
    }
    Write-Host 'Opened VPS Claude accounts in Orca.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'Confirm Tailscale is connected and Orca can reach the remote host.'
    exit 1
}
