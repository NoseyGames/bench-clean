$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@(Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.IsResourcePackage } | ForEach-Object {
    [PSCustomObject]@{ name=$_.Name; package=$_.PackageFullName; location=$_.InstallLocation; protected=[bool]$_.NonRemovable; publisher=$_.Publisher }
}) | ConvertTo-Json -Depth 4 -Compress
