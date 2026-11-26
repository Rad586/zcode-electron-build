param(
  [ValidateSet('Apply', 'Validate')][string]$Phase,
  [switch]$SvgScale,
  [switch]$FlexLayout,
  [switch]$CurrentColor
)

$ErrorActionPreference = 'Stop'
$experiments = @{
  'svg-scale-invalidation' = @('svg-scale-invalidation', 'svg-scale', 'ZCODE_SVG_PROFILE')
  'flex-layout-space' = @('flex-layout-space', 'flex-layout', 'ZCODE_FLEX_PROFILE')
  'direct-currentcolor' = @('currentcolor', 'currentcolor', 'ZCODE_CURRENTCOLOR_PROFILE')
}
if ($Phase -eq 'Apply') {
  $selected = @(
    if ($SvgScale) { 'svg-scale-invalidation' }
    if ($FlexLayout) { 'flex-layout-space' }
    if ($CurrentColor) { 'direct-currentcolor' }
  )
  if ($selected.Count -gt 1) { throw 'Select only one performance experiment' }
  $svgArgs = @()
  $patch = 'svg-clean-paint-record-cache'
  if ($selected.Count) {
    $svgArgs = @('--static-only')
    $patch = $selected[0]
  }
  python "$PSScriptRoot\apply-svg-lifecycle.py" D:\ec\src @svgArgs
  if ($LASTEXITCODE) { throw 'SVG lifecycle patch failed' }
  if ($selected.Count) {
    python "$PSScriptRoot\apply-$($experiments[$patch][0]).py" D:\ec\src
    if ($LASTEXITCODE) { throw "$patch patch failed" }
  }
  $env:ZCODE_SVG_PATCH = $patch
  "ZCODE_SVG_PATCH=$patch" | Add-Content $env:GITHUB_ENV
  return
}

$env:ZCODE_SVG_PROFILE = 'D:\ec\svg-profile'
& D:\ec\src\out\Release\electron.exe "$PSScriptRoot\svg-smoke.cjs" | Tee-Object -FilePath D:\ec\svg-smoke.json
if ($LASTEXITCODE) { throw 'SVG lifecycle behavior checks failed' }
$patch = $env:ZCODE_SVG_PATCH
if ($experiments.ContainsKey($patch)) {
  $prefix = $experiments[$patch][1]
  Set-Item "Env:$($experiments[$patch][2])" "D:\ec\$prefix-profile"
  & D:\ec\src\out\Release\electron.exe "$PSScriptRoot\$prefix-smoke.cjs" | Tee-Object -FilePath "D:\ec\$prefix-smoke.json"
  if ($LASTEXITCODE) { throw "$patch behavior checks failed" }
} elseif ($patch -ne 'svg-clean-paint-record-cache') {
  throw "Unknown kernel experiment: $patch"
}
