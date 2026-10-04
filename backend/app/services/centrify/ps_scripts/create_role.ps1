# Zone'da yeni rol oluşturur.
# Parametreler: $ZoneDN, $RoleName, $Description
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)][string]$ZoneDN,
    [Parameter(Mandatory=$true)][string]$RoleName,
    [Parameter(Mandatory=$false)][string]$Description = ""
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib
bind_to_dc
select_zone "$ZoneDN"
new_role "$RoleName"
if {"$Description" ne ""} { set_role_field description "$Description" }
save_role
set guid [get_role_field objectGUID]
set dn [get_role_field dn]
puts "RESULT_JSON:{`"success`":true,`"name`":`"$RoleName`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`"}"
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
