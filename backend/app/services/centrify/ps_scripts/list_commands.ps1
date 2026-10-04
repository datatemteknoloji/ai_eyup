# Zone içindeki komut/right tanımlarını ADEdit ile listeler.
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

set cmds [list_dz_commands]
foreach c `$cmds {
    select_dz_command `$c
    set desc [get_dz_command_field description]
    set guid [get_dz_command_field objectGUID]
    set dn [get_dz_command_field dn]
    set path [get_dz_command_field command]
    set match [get_dz_command_field matchtype]
    set runas [get_dz_command_field runasuser]
    set runasgrp [get_dz_command_field runasgroup]
    set auth [get_dz_command_field authentication]
    puts "CMD_JSON:{`"name`":`"`$c`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"command_path`":`"`$path`",`"match_type`":`"`$match`",`"run_as_user`":`"`$runas`",`"run_as_group`":`"`$runasgrp`",`"auth_type`":`"`$auth`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $lines = $raw | Where-Object { $_ -match "^CMD_JSON:" }
    $cmds = @()
    foreach ($line in $lines) {
        $json = $line -replace "^CMD_JSON:", ""
        $obj = $json | ConvertFrom-Json
        $cmds += $obj
    }
    $cmds | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
