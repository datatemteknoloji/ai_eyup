# Bir rolden komut/right kaldırır.
# Parametreler: $ZoneDN, $RoleName, $CommandName
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN,
    [Parameter(Mandatory=$true)]
    [string]$RoleName,
    [Parameter(Mandatory=$true)]
    [string]$CommandName
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc
select_zone "$ZoneDN"

# Rolü seç
set roles [list_dz_roles]
set roleFound 0
foreach r `$roles {
    if {`$r eq "$RoleName"} {
        set roleFound 1
        break
    }
}
if {!`$roleFound} {
    puts "CMD_JSON:{`"success`":false,`"error`":`"Rol bulunamadı: $RoleName`"}"
    exit 0
}

select_dz_role "$RoleName"
set currentRights [get_dz_role_field rights]

# Komut rolde var mı?
set cmdFound 0
foreach cr `$currentRights {
    if {`$cr eq "$CommandName"} {
        set cmdFound 1
        break
    }
}
if {!`$cmdFound} {
    puts "CMD_JSON:{`"success`":false,`"error`":`"Komut bu rolde mevcut değil: $CommandName`"}"
    exit 0
}

remove_command_from_role "$CommandName"
save_dz_role

puts "CMD_JSON:{`"success`":true,`"role`":`"$RoleName`",`"command`":`"$CommandName`",`"message`":`"Komut rolden kaldırıldı`"}"
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
