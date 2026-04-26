param(
    [string]$Source = "",
    [string]$Out = "",
    [double]$Scale = 0.015625,
    [switch]$Clean,
    [switch]$ReverseWinding
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "extract_gfx_models.py"
$arguments = @($scriptPath, "--scale", $Scale.ToString([Globalization.CultureInfo]::InvariantCulture))

if ($Source -ne "") {
    $arguments += @("--source", $Source)
}

if ($Out -ne "") {
    $arguments += @("--out", $Out)
}

if ($Clean) {
    $arguments += "--clean"
}

if ($ReverseWinding) {
    $arguments += "--reverse-winding"
}

python @arguments
