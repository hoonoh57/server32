[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$extensions = @('.vb', '.vbproj', '.sln', '.config', '.xml', '.json', '.md', '.ps1', '.bat')
$failures = New-Object System.Collections.Generic.List[string]

$files = Get-ChildItem -LiteralPath $repoRoot -Recurse -File | Where-Object {
  $_.FullName -notmatch '[\\/](\.git|bin|obj|packages|lib)[\\/]' -and
  ($extensions -contains $_.Extension.ToLowerInvariant())
}

foreach ($file in $files) {
  $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
  $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
  $offset = if ($hasBom) { 3 } else { 0 }

  try {
    $text = $strictUtf8.GetString($bytes, $offset, $bytes.Length - $offset)
  }
  catch {
    $failures.Add("Invalid UTF-8: $($file.FullName)")
    continue
  }

  if ($text.IndexOf([char]0xFFFD) -ge 0 -or $text -match '[\u0080-\u009F]') {
    $failures.Add("Suspicious replacement/control character: $($file.FullName)")
  }

  if ($text -match '[\u00C0-\u00FF].*[\u00C0-\u00FF]') {
    $failures.Add("Possible byte-expanded mojibake: $($file.FullName)")
  }
}

if ($failures.Count -gt 0) {
  $failures | ForEach-Object { Write-Error $_ }
  throw 'Encoding verification failed. Fix the reported source text; do not blindly re-encode mojibake.'
}

Write-Host "Encoding verification passed: $($files.Count) UTF-8 text files."

