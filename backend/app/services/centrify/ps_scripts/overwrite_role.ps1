# Hedef rolün komutlarını kaynak rolün komutlarıyla üzerine yazar.
# Parametreler: $SrcZoneDN, $SrcRoleName, $DstZoneDN, $DstRoleName
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)][string]$SrcZoneDN,
    [Parameter(Mandatory=$true)][string]$SrcRoleName,
    [Parameter(Mandatory=$true)][string]$DstZoneDN,
    [Parameter(Mandatory=$true)][string]$DstRoleName
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib
bind_to_dc

# Kaynak rolün komutlarını oku
select_zone "$SrcZoneDN"
select_role "$SrcRoleName"
set src_rights [get_role_rights]

# Hedef rolün mevcut komutlarını sil
select_zone "$DstZoneDN"
select_role "$DstRoleName"
set dst_rights [get_role_rights]
foreach r `$dst_rights {
    remove_role_right `$r
}

# Kaynak komutları ekle
foreach r `$src_rights {
    add_role_right `$r
}
save_role

set removed [llength `$dst_rights]
set added [llength `$src_rights]
puts "RESULT_JSON:{`"success`":true,`"target`":`"$DstRoleName`",`"removed`":`$removed,`"added`":`$added}"
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
