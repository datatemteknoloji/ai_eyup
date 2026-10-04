# Rolü komutlarıyla birlikte başka zone'a veya aynı zone'a klonlar.
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
set src_desc [get_role_field description]
set src_rights [get_role_rights]

# Hedef zone'da yeni rol oluştur
select_zone "$DstZoneDN"
new_role "$DstRoleName"
set_role_field description "`$src_desc"
save_role

# Komutları kopyala
foreach r `$src_rights {
    add_role_right `$r
}
save_role

set guid [get_role_field objectGUID]
set dn [get_role_field dn]
set cmd_count [llength `$src_rights]
puts "RESULT_JSON:{`"success`":true,`"name`":`"$DstRoleName`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"commands_copied`":`$cmd_count}"
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
