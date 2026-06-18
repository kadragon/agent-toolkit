<#
.SYNOPSIS
    Convert a single .hwp file to .hwpx using Hancom COM automation, then delete the original.
.PARAMETER Path
    Absolute or relative path to the .hwp file.
.OUTPUTS
    Writes the resulting .hwpx path to stdout on success.
.NOTES
    Requires Hancom Office installed (HWPFrame.HwpObject COM ProgID must be registered).
    Original .hwp is deleted only after the .hwpx is verified non-empty.
#>
param(
    [Parameter(Mandatory)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$hwpPath  = (Resolve-Path $Path).Path
$hwpxPath = [System.IO.Path]::ChangeExtension($hwpPath, ".hwpx")

$hwp = $null
try {
    $hwp = New-Object -ComObject HWPFrame.HwpObject
    $hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")

    $opened = $hwp.Open($hwpPath, "HWP", "forceopen:true")
    if (-not $opened) { throw "HWP Open() returned false for: $hwpPath" }

    $saved = $hwp.SaveAs($hwpxPath, "HWPX", "")
    if (-not $saved) { throw "HWP SaveAs() returned false for: $hwpxPath" }
} finally {
    if ($hwp) { $hwp.Quit() }
}

# Gate deletion on verified non-empty output
if ((Test-Path $hwpxPath) -and (Get-Item $hwpxPath).Length -gt 0) {
    Remove-Item $hwpPath -Force
    Write-Output $hwpxPath
} else {
    throw "Conversion failed — output missing or empty. Original preserved: $hwpPath"
}
