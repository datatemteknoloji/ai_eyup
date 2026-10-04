# Zone'dan komut/right tanımı siler.
# Parametreler: $ZoneDN, $CommandName
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN,
    [Parameter(Mandatory=$true)]
    [string]$CommandName
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc
select_zone "$ZoneDN"

# Komutun varlığını kontrol et
set existing [list_dz_commands]
set found 0
foreach c `$existing {
    if {`$c eq "$CommandName"} {
        set found 1
        break
    }
}

if {!`$found} {
    puts "CMD_JSON:{`"success`":false,`"error`":`"Komut bulunamadı: $CommandName`"}"
    exit 0
}

# Komutun role bağlı olup olmadığını kontrol et
set roles [list_dz_roles]
set bound_roles [list]
foreach r `$roles {
    select_dz_role `$r
    set cmds [get_dz_role_field rights]
    foreach rc `$cmds {
        if {`$rc eq "$CommandName"} {
            lappend bound_roles `$r
            break
        }
    }
}

if {[llength `$bound_roles] > 0} {
    set roleList [join `$bound_roles ", "]
    puts "CMD_JSON:{`"success`":false,`"error`":`"Komut rollere bağlı, önce kaldırın: `$roleList`",`"bound_roles`":`$bound_roles}"
    exit 0
}

# Komutu sil
select_dz_command "$CommandName"
delete_dz_command

puts "CMD_JSON:{`"success`":true,`"name`":`"$CommandName`",`"message`":`"Komut silindi`"}"
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
