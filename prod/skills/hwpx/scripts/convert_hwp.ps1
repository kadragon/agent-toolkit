<#
.SYNOPSIS
    Convert a single .hwp file to .hwpx using Hancom COM automation, then delete the original.
.PARAMETER Path
    Absolute or relative path to the .hwp file.
.PARAMETER Force
    Overwrite the target .hwpx if it already exists. Without this flag the script aborts
    when a same-name .hwpx is already present, protecting against accidental data loss.
.OUTPUTS
    Writes the resulting .hwpx path to stdout on success.
    Exits non-zero and writes the error message to stderr on failure.
    Original .hwp is deleted only after the .hwpx is verified non-empty.
.NOTES
    Requires Hancom Office installed (HWPFrame.HwpObject COM ProgID must be registered).
    Uses forceopen:true — only call on trusted input files (macros are not blocked).
#>
param(
    [Parameter(Mandatory)]
    [string]$Path,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Validate input exists
if (-not (Test-Path $Path)) {
    throw "File not found: $Path"
}

$hwpPath = (Resolve-Path $Path).Path

# Enforce .hwp extension — avoids destructive same-name overwrite on wrong input
$ext = [System.IO.Path]::GetExtension($hwpPath)
if ($ext -ine '.hwp') {
    throw "Expected a .hwp file, got: $hwpPath"
}

$hwpxPath = [System.IO.Path]::ChangeExtension($hwpPath, ".hwpx")

# Guard against overwriting an existing .hwpx unless --Force is given
if ((Test-Path $hwpxPath) -and -not $Force) {
    throw "Target already exists: $hwpxPath. Use -Force to overwrite."
}

$hwp = $null
try {
    $hwp = New-Object -ComObject HWPFrame.HwpObject
    $reg = $hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
    if (-not $reg) {
        Write-Warning "RegisterModule('FilePathCheckDLL') failed — proceeding anyway; Open() with forceopen:true works without it on non-macro documents."
    }

    $opened = $hwp.Open($hwpPath, "HWP", "forceopen:true")
    if (-not $opened) { throw "HWP Open() returned false for: $hwpPath" }

    $saved = $hwp.SaveAs($hwpxPath, "HWPX", "")
    if (-not $saved) { throw "HWP SaveAs() returned false for: $hwpxPath" }
} finally {
    # Quit in its own try/catch so a COM error here doesn't mask the real exception
    if ($hwp) { try { $hwp.Quit() } catch {} }
}

# Gate deletion on verified non-empty output
if ((Test-Path $hwpxPath) -and (Get-Item $hwpxPath).Length -gt 0) {
    Remove-Item $hwpPath -Force
    Write-Output $hwpxPath
} else {
    throw "Conversion failed — output missing or empty. Original preserved: $hwpPath"
}
