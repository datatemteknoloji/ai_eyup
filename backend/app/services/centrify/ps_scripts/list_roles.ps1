# Zone içindeki rolleri ADEdit ile listeler (rights + login bayrakları dahil).
# Parametre: $ZoneDN
# Not: Tam envanter için list_zone_inventory.ps1 tercih edilir (tek oturum).

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN
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

set roles [list_roles]
foreach r `$roles {
    select_role `$r
    set desc [safe_get get_role_field description]
    set guid [safe_get get_role_field objectGUID]
    set dn [safe_get get_role_field dn]
    set sys [safe_get get_role_field systemRole]
    set pw [safe_get get_role_field AllowPasswordLogin]
    if {`$pw eq ""} { set pw [safe_get get_role_field allowPasswordLogin] }
    set sso [safe_get get_role_field AllowSSOLogin]
    if {`$sso eq ""} { set sso [safe_get get_role_field allowSSOLogin] }
    set mfa [safe_get get_role_field RequireMultiFactorAuth]
    if {`$mfa eq ""} { set mfa [safe_get get_role_field requireMFA] }
    set local [safe_get get_role_field AllowLocalAccount]
    set nrs [safe_get get_role_field NonRestrictedShell]
    set uv [safe_get get_role_field UserVisible]
    set console [safe_get get_role_field AllowConsoleLogin]
    set remote [safe_get get_role_field AllowRemoteLogin]
    set psrem [safe_get get_role_field AllowPowerShellRemote]
    set rescue [safe_get get_role_field AllowRescueRights]
    set audit [safe_get get_role_field AuditLevel]
    set rights [safe_get get_role_rights]
    set rlist [join `$rights "||"]
    puts "ROLE_JSON:{`"name`":`"`$r`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"is_system_role`":`"`$sys`",`"password_login_allowed`":`"`$pw`",`"sso_login_allowed`":`"`$sso`",`"require_mfa`":`"`$mfa`",`"allow_local_accounts`":`"`$local`",`"non_restricted_shell`":`"`$nrs`",`"user_visible`":`"`$uv`",`"console_login_allowed`":`"`$console`",`"remote_login_allowed`":`"`$remote`",`"powershell_remote_allowed`":`"`$psrem`",`"rescue_login_allowed`":`"`$rescue`",`"audit_level`":`"`$audit`",`"rights`":`"`$rlist`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $roles = @()
    foreach ($line in $raw) {
        if ("$line" -match "^ROLE_JSON:") {
            $json = "$line" -replace "^ROLE_JSON:", ""
            try { $roles += ($json | ConvertFrom-Json) } catch { }
        }
    }
    $roles | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
