param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$nativeInstallRoot = Split-Path -Parent $PSScriptRoot
$nativeConfigPath = Join-Path $nativeInstallRoot 'config.json'
if ($ConfigPath) { $nativeConfigPath = [IO.Path]::GetFullPath($ConfigPath); $nativeInstallRoot = Split-Path -Parent $nativeConfigPath }
$nativeRoot = Join-Path $nativeInstallRoot 'native'
try {
    $nativeConfig = Get-Content -LiteralPath $nativeConfigPath -Raw | ConvertFrom-Json
    $mediaSettingsPath = Join-Path $nativeRoot 'media-tools.json'
    if (Test-Path -LiteralPath $mediaSettingsPath) {
        $mediaSettings = Get-Content -LiteralPath $mediaSettingsPath -Raw | ConvertFrom-Json
        $nativeConfig.native | Add-Member -MemberType NoteProperty -Name media_tools -Value $mediaSettings -Force
    }
    $nativeBlocked = @('0.0.0.0/2','64.0.0.0/3','96.0.0.0/6','100.0.0.0/10','100.128.0.0/9','101.0.0.0/8','102.0.0.0/7','104.0.0.0/5','112.0.0.0/5','120.0.0.0/6','124.0.0.0/7','126.0.0.0/8','128.0.0.0/1','::/1','8000::/1')
    $nativePrograms = @{godot=$nativeConfig.native.godot_executable;blender=$nativeConfig.native.blender_executable;go=$nativeConfig.native.go_executable;vroid=$nativeConfig.native.vroid_executable;unity=$nativeConfig.native.unity_executable;'unity-cli'=$nativeConfig.native.unity_cli_executable}
    foreach ($mediaName in @('python','node','ffmpeg','ffprobe','chromium')) {
        $mediaValue = $nativeConfig.native.media_tools.($mediaName + '_executable')
        if ($mediaValue) { $nativePrograms['media-' + $mediaName] = $mediaValue }
    }
    foreach ($nativeProperty in $nativeConfig.native.server_executables.PSObject.Properties) {
        if ($nativeProperty.Name -notmatch '^[a-z0-9][a-z0-9_-]{0,63}$') { throw 'Invalid project id.' }
        $nativePrograms['server-' + $nativeProperty.Name] = $nativeProperty.Value
    }
    foreach ($nativeEngine in $nativePrograms.Keys) {
        if (-not $nativePrograms[$nativeEngine]) { continue }
        $nativeExe = [IO.Path]::GetFullPath($nativePrograms[$nativeEngine])
        if ($nativeEngine -like 'media-*') {
            $mediaRoot = [IO.Path]::GetFullPath($nativeConfig.native.media_tools.root).TrimEnd('\','/')
            if ([IO.Path]::GetFileName($mediaRoot) -ne 'LocalGpuMedia' -or -not $nativeExe.StartsWith($mediaRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Media tools must be dedicated copies in LocalGpuMedia.' }
            if (-not (Test-Path -LiteralPath $nativeExe -PathType Leaf)) { throw 'Managed media executable is missing.' }
            if ($nativeEngine -eq 'media-chromium') {
                if ([IO.Path]::GetFileName($nativeExe) -notin @('headless_shell.exe','chrome-headless-shell.exe')) { throw 'Expected dedicated Chromium headless shell.' }
            } elseif ($nativeExe -ne (Join-Path $mediaRoot ($nativeEngine.Substring(6) + '.exe'))) { throw 'Unexpected media executable path.' }
        } elseif ($nativeEngine -like 'server-*') {
            $nativeExpectedServer = [IO.Path]::GetFullPath((Join-Path $nativeRoot ('servers\' + $nativeEngine.Substring(7) + '.exe')))
            if ($nativeExe -ne $nativeExpectedServer) { throw 'Invalid managed game-server path.' }
        } else {
            if (-not (Test-Path -LiteralPath $nativeExe -PathType Leaf)) { throw 'Managed renderer/compiler executable is missing.' }
            if ([IO.Path]::GetFileName($nativeExe) -notin @('Godot-LocalGpu.exe','blender-local-gpu.exe','go-local-gpu.exe','VRoidStudio-LocalGpu.exe','Unity-LocalGpu.exe','unity-cli-local-gpu.exe')) { throw 'Refusing to change network policy for a normal application executable.' }
        }
        $nativeRuleName = 'LocalGpuBridge-' + $nativeEngine + '-Private'
        $nativeOldRule = Get-NetFirewallRule -Name $nativeRuleName -ErrorAction SilentlyContinue
        if ($nativeOldRule) { $nativeOldRule | Remove-NetFirewallRule }
        New-NetFirewallRule -Name $nativeRuleName -DisplayName ('Local GPU Bridge - ' + $nativeEngine + ' - block external network') -Direction Outbound -Program $nativeExe -Action Block -Enabled True -Profile Any -Protocol Any -RemoteAddress $nativeBlocked | Out-Null
    }
    New-Item -ItemType Directory -Path $nativeRoot -Force | Out-Null
    @{ok=$true;completed_at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $nativeRoot 'privacy-setup.json') -Encoding utf8
} catch {
    New-Item -ItemType Directory -Path $nativeRoot -Force | Out-Null
    ($_ | Format-List * -Force | Out-String) | Set-Content -LiteralPath (Join-Path $nativeRoot 'privacy-setup-error.txt') -Encoding utf8
    @{ok=$false;message='Windows could not install renderer firewall rules. Run this setup as administrator.'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $nativeRoot 'privacy-setup.json') -Encoding utf8
    exit 1
}
