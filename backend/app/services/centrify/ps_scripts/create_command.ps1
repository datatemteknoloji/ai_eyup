# Zone'da yeni komut/right tanımı oluşturur.
# Parametreler: $ZoneDN, $CommandName, $CommandPath, $MatchType, $RunAsUser, $RunAsGroup, $AuthType, $Description
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN,
    [Parameter(Mandatory=$true)]
    [string]$CommandName,
    [Parameter(Mandatory=$true)]
    [string]$CommandPath,
    [string]$MatchType = "glob",
    [string]$RunAsUser = "root",
    [string]$RunAsGroup = "",
    [string]$AuthType = "password",
    [string]$Description = ""
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc
select_zone "$ZoneDN"

# Aynı isimde komut var mı kontrol et
set existing [list_dz_commands]
foreach c `$existing {
    if {`$c eq "$CommandName"} {
        puts "CMD_JSON:{`"success`":false,`"error`":`"Bu isimde komut zaten mevcut: $CommandName`"}"
        exit 0
    }
}

# Yeni komut oluştur
new_dz_command "$CommandName"
set_dz_command_field description "$Description"
set_dz_command_field command "$CommandPath"
set_dz_command_field matchtype "$MatchType"
set_dz_command_field runasuser "$RunAsUser"
set_dz_command_field runasgroup "$RunAsGroup"
set_dz_command_field authentication "$AuthType"
save_dz_command

# Oluşturulan komutun bilgilerini al
select_dz_command "$CommandName"
set guid [get_dz_command_field objectGUID]
set dn [get_dz_command_field dn]

puts "CMD_JSON:{`"success`":true,`"name`":`"$CommandName`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"command_path`":`"$CommandPath`",`"match_type`":`"$MatchType`",`"run_as_user`":`"$RunAsUser`",`"auth_type`":`"$AuthType`"}"
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $lines = $raw | Where-Object { $_ -match "^CMD_JSON:" }
    if ($lines) {
        $json = ($lines | Select-Object -Last 1) -replace "^CMD_JSON:", ""
        $json
    } else {
        @{ success = $false; error = "ADEdit çıktısı alınamadı" } | ConvertTo-Json -Depth 3
    }
} catch {
    @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
