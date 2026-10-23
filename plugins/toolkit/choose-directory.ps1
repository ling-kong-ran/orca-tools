$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$folderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
$folderOwner = New-Object System.Windows.Forms.Form
try {
    $folderDialog.Description = 'Choose a download folder'
    $folderDialog.ShowNewFolderButton = $true
    if ($folderDialog.PSObject.Properties.Name -contains 'UseDescriptionForTitle') {
        $folderDialog.UseDescriptionForTitle = $true
    }
    $initialFolder = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:ORCA_TOOLKIT_FOLDER_BASE64))
    if ($initialFolder -and (Test-Path -LiteralPath $initialFolder -PathType Container)) {
        $folderDialog.SelectedPath = $initialFolder
    }
    $folderOwner.ShowInTaskbar = $false
    $folderOwner.TopMost = $true
    $folderOwner.StartPosition = 'CenterScreen'
    $folderOwner.Size = New-Object System.Drawing.Size(1, 1)
    $folderOwner.Opacity = 0
    $folderOwner.Show()
    $folderOwner.Activate()
    if ($folderDialog.ShowDialog($folderOwner) -eq [Windows.Forms.DialogResult]::OK) {
        @{cancelled=$false;path=$folderDialog.SelectedPath} | ConvertTo-Json -Compress
    } else {
        @{cancelled=$true} | ConvertTo-Json -Compress
    }
} finally {
    $folderDialog.Dispose()
    $folderOwner.Dispose()
}
