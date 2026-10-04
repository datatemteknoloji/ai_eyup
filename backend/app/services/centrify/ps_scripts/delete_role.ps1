# Zone'dan rol siler.
# Parametreler: $ZoneDN, $RoleName
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)][string]$ZoneDN,
    [Parameter(Mandatory=$true)][string]$RoleName
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib
bind_to_dc
select_zone "$ZoneDN"
select_role "$RoleName"
delete_role
puts "RESULT_JSON:{`"success`":true,`"name`":`"$RoleName`",`"action`":`"deleted`"}"
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $line = $raw | Where-Object { $_ -match "^RESULT_JSON:" } | Select-Object -First 1
    if ($line) {
        ($line -replace "^RESULT_JSON:","") | ConvertFrom-Json | ConvertTo-Json -Depth 3
    } else {
        @{ success = $false; error = ($raw | Out-String).Trim() } | ConvertTo-Json -Depth 3
    }
} catch {
    @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
