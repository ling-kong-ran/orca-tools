$ErrorActionPreference = 'Stop'
$options = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:ORCA_DEPLOY_LOCAL_OPTIONS)) | ConvertFrom-Json
$appDirectory = [IO.Path]::GetFullPath($options.install_dir)
$sourceDirectory = [IO.Path]::GetFullPath($options.source_root)
$reportFile = [IO.Path]::GetFullPath($options.report)
function Report($status, $message) {
    $value = @{status=$status;message=$message;updated_utc=[DateTime]::UtcNow.ToString('o')}
    $value | ConvertTo-Json -Compress | Set-Content -LiteralPath ($reportFile + '.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($reportFile + '.tmp') -Destination $reportFile -Force
}
function Download($url, $destination) {
    if (-not $url.StartsWith('https://')) { throw 'HTTPS required.' }
    Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing
}
try {
    if ($appDirectory -eq [IO.Path]::GetPathRoot($appDirectory)) { throw 'Select a specific application directory.' }
    if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'plugins\toolkit\Install.cjs'))) { throw 'Installer source is missing.' }
    New-Item -ItemType Directory -Path $appDirectory -Force | Out-Null
    $downloadsDirectory = Join-Path $appDirectory 'installers'
    New-Item -ItemType Directory -Path $downloadsDirectory -Force | Out-Null
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $nodeExecutable = if ($nodeCommand) { $nodeCommand.Source } else { $null }
    if (-not $nodeExecutable) {
        Report 'running' '正在准备 Node LTS 独立运行时。'
        $releases = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json'
        $release = $releases | Where-Object { $_.lts -and $_.files -contains 'win-x64-zip' } | Select-Object -First 1
        if (-not $release -or $release.version -notmatch '^v\d+\.\d+\.\d+$') { throw 'No supported Node LTS release.' }
        $archiveName = 'node-' + $release.version + '-win-x64.zip'
        $baseUrl = 'https://nodejs.org/dist/' + $release.version + '/'
        $hashText = (Invoke-WebRequest -Uri ($baseUrl+'SHASUMS256.txt') -UseBasicParsing).Content
        $hashLine = @($hashText -split "`n" | Where-Object { $_ -match ('^[a-f0-9]{64}\s+'+[regex]::Escape($archiveName)+'\s*$') })
        if ($hashLine.Count -ne 1) { throw 'Node checksum not found.' }
        $expectedHash = ($hashLine[0] -split '\s+')[0]
        $nodeArchive = Join-Path $downloadsDirectory $archiveName
        Download ($baseUrl+$archiveName) $nodeArchive
        if ((Get-FileHash -LiteralPath $nodeArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Node checksum mismatch.' }
        $runtimeDirectory = Join-Path $appDirectory 'runtime'
        New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
        Expand-Archive -LiteralPath $nodeArchive -DestinationPath $runtimeDirectory -Force
        $nodeExecutable = Join-Path $runtimeDirectory ('node-'+$release.version+'-win-x64\node.exe')
    }
    $tailscaleExecutable = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (-not (Test-Path -LiteralPath $tailscaleExecutable)) {
        Report 'needs-user' '请在打开的官方 Tailscale 安装页面完成 Windows 安装与登录，然后重新执行本机准备。'
        Start-Process 'https://tailscale.com/download/windows' -WindowStyle Hidden
        exit 0
    }
    $orcaResources = Join-Path $env:LOCALAPPDATA 'Programs\orca\resources'
    $orcaExecutable = Join-Path $orcaResources 'bin\orca.exe'
    if (-not (Test-Path -LiteralPath $orcaExecutable)) {
        Report 'needs-user' '请在打开的官方 Orca 页面完成 Windows 安装，之后重新执行本机准备。'
        Start-Process 'https://www.onorca.dev/docs/install' -WindowStyle Hidden
        exit 0
    }
    Report 'running' '正在构建并安装 Toolkit；现有 GPU Bridge 不重启。'
    & $nodeExecutable (Join-Path $sourceDirectory 'scripts\build-toolkit-ui.cjs') *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Toolkit build failed.' }
    & $nodeExecutable (Join-Path $sourceDirectory 'plugins\toolkit\Install.cjs') *> $null
    if ($LASTEXITCODE -ne 0) {
        Report 'needs-user' ('当前 Orca 版本需要手动导入插件：Settings → Plugins → Import，选择 '+(Join-Path $sourceDirectory 'plugins\toolkit')+'。')
        exit 0
    }
    Report 'needs-user' 'Toolkit 文件已安装。请在 Orca Settings → Plugins 审核并启用，然后从统一入口的部署中心继续。'
} catch {
    Report 'needs-attention' '本机准备未完成。检查网络、所选目录与官方安装器；不会返回原始身份或凭据日志。'
    exit 1
}
