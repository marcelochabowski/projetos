param(
    [string]$Source = "",
    [string]$Out = "",
    [switch]$Clean,
    [switch]$IncludeDiscImage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "extract_ps1_assets.py"
$arguments = @($scriptPath)

if ($Source -ne "") {
    $arguments += @("--source", $Source)
}

if ($Out -ne "") {
    $arguments += @("--out", $Out)
}

if ($Clean) {
    $arguments += "--clean"
}

if ($IncludeDiscImage) {
    $arguments += "--include-disc-image"
}

python @arguments
