# Zone listesini ADEdit ile çeker.
# Çıktı: JSON array
# Parametre yok — tüm zone'ları döndürür.

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc

set zones [get_zones]
foreach z `$zones {
    select_zone `$z
    set dn [get_zone_field dn]
    set name [get_zone_field name]
    set desc [get_zone_field description]
    set ztype [get_zone_field zonetype]
    set parent_dn [get_zone_field parentzone]
    set guid [get_zone_field objectGUID]
    puts "ZONE_JSON:{`"ad_dn`":`"`$dn`",`"name`":`"`$name`",`"description`":`"`$desc`",`"zone_type`":`"`$ztype`",`"parent_zone_dn`":`"`$parent_dn`",`"ad_guid`":`"`$guid`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $lines = $raw | Where-Object { $_ -match "^ZONE_JSON:" }
    $zones = @()
    foreach ($line in $lines) {
        $json = $line -replace "^ZONE_JSON:", ""
        $obj = $json | ConvertFrom-Json
        $zones += $obj
    }
    $zones | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
