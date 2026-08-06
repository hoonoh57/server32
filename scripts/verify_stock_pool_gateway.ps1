param(
    [string]$BaseUrl = "http://127.0.0.1:8082",
    [string[]]$Names = @("아로마티카", "져스텍", "금호타이어")
)

$ErrorActionPreference = "Stop"

if ($Names.Count -eq 0) {
    throw "Names must contain at least one symbol name."
}

$uri = $BaseUrl.TrimEnd('/') + "/api/stock-pool/symbols/resolve"
$body = @{ names = $Names } | ConvertTo-Json -Depth 4 -Compress

Write-Host "[stock-pool gateway smoke test]"
Write-Host "POST $uri"
Write-Host "names=$($Names -join ', ')"

try {
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri $uri `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
}
catch {
    throw "Gateway request failed: $($_.Exception.Message)"
}

if (-not $response.Success) {
    throw "Gateway returned failure: $($response.Message)"
}

$data = $response.Data
if ($null -eq $data) {
    throw "Gateway response Data is missing."
}

Write-Host "source=$($data.source)"
Write-Host "resolved_count=$($data.resolved_count)"
Write-Host "rejected_count=$($data.rejected_count)"

if ($data.resolved) {
    $data.resolved |
        Select-Object name, code, market |
        Format-Table -AutoSize
}

if ($data.rejected) {
    Write-Host "Rejected:"
    $data.rejected |
        Select-Object input_index, name, reason |
        Format-Table -AutoSize
}

if ([int]$data.resolved_count -le 0) {
    throw "No names were resolved. Verify server32 .env and gate3.g3_symbol_master."
}

Write-Host "stock-pool gateway smoke test passed"
