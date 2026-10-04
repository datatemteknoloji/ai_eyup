# Zone içindeki computer role'leri ADEdit ile listeler.
# Parametre: $ZoneDN — zone distinguished name
# Çıktı: JSON array

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc
select_zone "$ZoneDN"

set croles [list_computer_roles]
foreach cr `$croles {
    select_computer_role `$cr
    set desc [get_computer_role_field description]
    set guid [get_computer_role_field objectGUID]
    set dn [get_computer_role_field dn]
    puts "CR_JSON:{`"name`":`"`$cr`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $lines = $raw | Where-Object { $_ -match "^CR_JSON:" }
    $croles = @()
    foreach ($line in $lines) {
        $json = $line -replace "^CR_JSON:", ""
        $obj = $json | ConvertFrom-Json
        $croles += $obj
    }
    $croles | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
