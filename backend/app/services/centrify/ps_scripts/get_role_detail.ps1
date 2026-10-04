# Rolün detaylarını ve bağlı komutlarını getirir.
# Parametreler: $ZoneDN, $RoleName
# Çıktı: JSON

param(
    [Parameter(Mandatory=$true)][string]$ZoneDN,
    [Parameter(Mandatory=$true)][string]$RoleName
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib
proc safe_get {cmd args} {
    if {[catch {eval `$cmd `$args} v]} { return "" }
    return `$v
}
bind_to_dc
select_zone "$ZoneDN"
select_role "$RoleName"
set desc [safe_get get_role_field description]
set guid [safe_get get_role_field objectGUID]
set dn [safe_get get_role_field dn]
set sys [safe_get get_role_field systemRole]
set pw [safe_get get_role_field AllowPasswordLogin]
set sso [safe_get get_role_field AllowSSOLogin]
set mfa [safe_get get_role_field RequireMultiFactorAuth]
set rights [safe_get get_role_rights]
puts "ROLE_DETAIL_START"
puts "name=$RoleName"
puts "description=`$desc"
puts "ad_guid=`$guid"
puts "ad_dn=`$dn"
puts "is_system=`$sys"
puts "password_login=`$pw"
puts "sso_login=`$sso"
puts "require_mfa=`$mfa"
foreach r `$rights {
    puts "RIGHT=`$r"
}
puts "ROLE_DETAIL_END"
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $inBlock = $false
    $role = @{
        name = ""; description = ""; ad_guid = ""; ad_dn = ""
        is_system_role = "false"; password_login_allowed = ""; sso_login_allowed = ""
        require_mfa = ""; rights = @()
    }
    foreach ($line in ($raw -split "`n")) {
        $line = ("$line").Trim()
        if ($line -eq "ROLE_DETAIL_START") { $inBlock = $true; continue }
        if ($line -eq "ROLE_DETAIL_END") { $inBlock = $false; continue }
        if ($inBlock) {
            if ($line -match "^name=(.*)") { $role.name = $Matches[1] }
            elseif ($line -match "^description=(.*)") { $role.description = $Matches[1] }
            elseif ($line -match "^ad_guid=(.*)") { $role.ad_guid = $Matches[1] }
            elseif ($line -match "^ad_dn=(.*)") { $role.ad_dn = $Matches[1] }
            elseif ($line -match "^is_system=(.*)") { $role.is_system_role = $Matches[1] }
            elseif ($line -match "^password_login=(.*)") { $role.password_login_allowed = $Matches[1] }
            elseif ($line -match "^sso_login=(.*)") { $role.sso_login_allowed = $Matches[1] }
            elseif ($line -match "^require_mfa=(.*)") { $role.require_mfa = $Matches[1] }
            elseif ($line -match "^RIGHT=(.*)") { $role.rights += $Matches[1] }
        }
    }
    $role | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
