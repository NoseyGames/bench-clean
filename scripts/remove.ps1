$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$pkg = @(Get-AppxPackage | Where-Object { $_.PackageFullName -eq $env:BENCH_PACKAGE })
if ($pkg.Count -ne 1) { throw 'Package is no longer installed. Refresh the app list.' }
if ($pkg[0].NonRemovable -or $pkg[0].IsFramework -or $pkg[0].IsResourcePackage) { throw 'This package is protected.' }
Remove-AppxPackage -Package $pkg[0].PackageFullName -ErrorAction Stop
if (Get-AppxPackage | Where-Object { $_.PackageFullName -eq $env:BENCH_PACKAGE }) { throw 'Windows still reports the package installed.' }
