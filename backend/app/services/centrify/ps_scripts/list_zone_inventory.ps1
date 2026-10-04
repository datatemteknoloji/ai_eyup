# Tek WinRM/ADEdit oturumunda zone envanteri — port/yoğunluk için birleştirilmiş okuma.
# Parametre: $ZoneDN
# Çıktı: JSON object { roles, commands, assignments, computers, unix_profiles, computer_roles }
#
# Not: ADEdit alan adları sürüme göre değişebilir; bilinmeyen alanlar boş bırakılır.

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

# ── Commands ──
set cmds [safe_get list_dz_commands]
foreach c `$cmds {
    select_dz_command `$c
    set desc [safe_get get_dz_command_field description]
    set guid [safe_get get_dz_command_field objectGUID]
    set dn [safe_get get_dz_command_field dn]
    set path [safe_get get_dz_command_field command]
    set match [safe_get get_dz_command_field matchtype]
    set runas [safe_get get_dz_command_field runasuser]
    set runasgrp [safe_get get_dz_command_field runasgroup]
    set auth [safe_get get_dz_command_field authentication]
    puts "CMD_JSON:{`"name`":`"`$c`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"command_path`":`"`$path`",`"match_type`":`"`$match`",`"run_as_user`":`"`$runas`",`"run_as_group`":`"`$runasgrp`",`"auth_type`":`"`$auth`"}"
}

# ── Roles (+ rights + login flags) ──
set roles [safe_get list_roles]
foreach r `$roles {
    select_role `$r
    set desc [safe_get get_role_field description]
    set guid [safe_get get_role_field objectGUID]
    set dn [safe_get get_role_field dn]
    set sys [safe_get get_role_field systemRole]
    # Login / system rights — sürüme göre alternatif alan adları
    set pw [safe_get get_role_field AllowPasswordLogin]
    if {`$pw eq ""} { set pw [safe_get get_role_field allowPasswordLogin] }
    if {`$pw eq ""} { set pw [safe_get get_role_field PasswordLoginAllowed] }
    set sso [safe_get get_role_field AllowSSOLogin]
    if {`$sso eq ""} { set sso [safe_get get_role_field allowSSOLogin] }
    set mfa [safe_get get_role_field RequireMultiFactorAuth]
    if {`$mfa eq ""} { set mfa [safe_get get_role_field requireMFA] }
    if {`$mfa eq ""} { set mfa [safe_get get_role_field RequireMFA] }
    set local [safe_get get_role_field AllowLocalAccount]
    if {`$local eq ""} { set local [safe_get get_role_field allowLocalAccounts] }
    set nrs [safe_get get_role_field NonRestrictedShell]
    if {`$nrs eq ""} { set nrs [safe_get get_role_field nonRestrictedShell] }
    set uv [safe_get get_role_field UserVisible]
    if {`$uv eq ""} { set uv [safe_get get_role_field userVisible] }
    set console [safe_get get_role_field AllowConsoleLogin]
    if {`$console eq ""} { set console [safe_get get_role_field consoleLoginAllowed] }
    set remote [safe_get get_role_field AllowRemoteLogin]
    if {`$remote eq ""} { set remote [safe_get get_role_field remoteLoginAllowed] }
    set psrem [safe_get get_role_field AllowPowerShellRemote]
    set rescue [safe_get get_role_field AllowRescueRights]
    set audit [safe_get get_role_field AuditLevel]
    if {`$audit eq ""} { set audit [safe_get get_role_field auditLevel] }
    set rights [safe_get get_role_rights]
    set rlist [join `$rights "||"]
    puts "ROLE_JSON:{`"name`":`"`$r`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"is_system_role`":`"`$sys`",`"password_login_allowed`":`"`$pw`",`"sso_login_allowed`":`"`$sso`",`"require_mfa`":`"`$mfa`",`"allow_local_accounts`":`"`$local`",`"non_restricted_shell`":`"`$nrs`",`"user_visible`":`"`$uv`",`"console_login_allowed`":`"`$console`",`"remote_login_allowed`":`"`$remote`",`"powershell_remote_allowed`":`"`$psrem`",`"rescue_login_allowed`":`"`$rescue`",`"audit_level`":`"`$audit`",`"rights`":`"`$rlist`"}"
}

# ── Role assignments ──
set assignments [safe_get list_role_assignments]
foreach a `$assignments {
    select_role_assignment `$a
    set role [safe_get get_role_assignment_field role]
    set atype [safe_get get_role_assignment_field assigneetype]
    set adn [safe_get get_role_assignment_field assignee]
    set aname [safe_get get_role_assignment_field assigneename]
    set scope [safe_get get_role_assignment_field scope]
    set sdn [safe_get get_role_assignment_field scopedn]
    set guid [safe_get get_role_assignment_field objectGUID]
    set dn [safe_get get_role_assignment_field dn]
    set stime [safe_get get_role_assignment_field starttime]
    set etime [safe_get get_role_assignment_field endtime]
    puts "RA_JSON:{`"role_name`":`"`$role`",`"assignee_type`":`"`$atype`",`"assignee_dn`":`"`$adn`",`"assignee_name`":`"`$aname`",`"scope_type`":`"`$scope`",`"scope_dn`":`"`$sdn`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"start_time`":`"`$stime`",`"end_time`":`"`$etime`"}"
}

# ── Computers ──
set comps [safe_get list_zone_computers]
if {`$comps eq ""} { set comps [safe_get list_computers] }
foreach c `$comps {
    if {[catch {select_zone_computer `$c}]} {
        catch {select_computer `$c}
    }
    set name [safe_get get_zone_computer_field name]
    if {`$name eq ""} { set name `$c }
    set fqdn [safe_get get_zone_computer_field dnsname]
    if {`$fqdn eq ""} { set fqdn [safe_get get_zone_computer_field dnsName] }
    if {`$fqdn eq ""} { set fqdn [safe_get get_zone_computer_field name] }
    set os [safe_get get_zone_computer_field operatingsystem]
    if {`$os eq ""} { set os [safe_get get_zone_computer_field operatingSystem] }
    set agent [safe_get get_zone_computer_field agentVersion]
    if {`$agent eq ""} { set agent [safe_get get_zone_computer_field centrifyDCVersion] }
    set guid [safe_get get_zone_computer_field objectGUID]
    set dn [safe_get get_zone_computer_field dn]
    puts "COMP_JSON:{`"name`":`"`$name`",`"fqdn`":`"`$fqdn`",`"os_type`":`"`$os`",`"agent_version`":`"`$agent`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`"}"
}

# ── UNIX profiles ──
set users [safe_get list_zone_users]
if {`$users eq ""} { set users [safe_get list_users] }
foreach u `$users {
    if {[catch {select_zone_user `$u}]} {
        catch {select_user `$u}
    }
    set uname [safe_get get_zone_user_field name]
    if {`$uname eq ""} { set uname `$u }
    set udn [safe_get get_zone_user_field dn]
    if {`$udn eq ""} { set udn [safe_get get_zone_user_field user] }
    set uid [safe_get get_zone_user_field uid]
    set gid [safe_get get_zone_user_field gid]
    set home [safe_get get_zone_user_field home]
    if {`$home eq ""} { set home [safe_get get_zone_user_field homedir] }
    set shell [safe_get get_zone_user_field shell]
    set gecos [safe_get get_zone_user_field gecos]
    set en [safe_get get_zone_user_field enabled]
    if {`$en eq ""} { set en "true" }
    puts "UNIX_JSON:{`"user_name`":`"`$uname`",`"user_dn`":`"`$udn`",`"uid`":`"`$uid`",`"gid`":`"`$gid`",`"home_dir`":`"`$home`",`"shell`":`"`$shell`",`"gecos`":`"`$gecos`",`"enabled`":`"`$en`"}"
}

# ── Computer roles ──
set croles [safe_get list_computer_roles]
foreach cr `$croles {
    select_computer_role `$cr
    set desc [safe_get get_computer_role_field description]
    set guid [safe_get get_computer_role_field objectGUID]
    set dn [safe_get get_computer_role_field dn]
    puts "CR_JSON:{`"name`":`"`$cr`",`"description`":`"`$desc`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`"}"
}
"@

function Convert-JsonLine($prefix, $lines) {
    $items = @()
    foreach ($line in $lines) {
        if ($line -match "^$prefix") {
            $json = $line -replace "^${prefix}", ""
            try { $items += ($json | ConvertFrom-Json) } catch { }
        }
    }
    return $items
}

try {
    $raw = $adeditScript | adedit 2>&1
    $textLines = @($raw | ForEach-Object { "$_" })
    $result = [ordered]@{
        zone_dn         = $ZoneDN
        roles           = @(Convert-JsonLine "ROLE_JSON:" $textLines)
        commands        = @(Convert-JsonLine "CMD_JSON:" $textLines)
        assignments     = @(Convert-JsonLine "RA_JSON:" $textLines)
        computers       = @(Convert-JsonLine "COMP_JSON:" $textLines)
        unix_profiles   = @(Convert-JsonLine "UNIX_JSON:" $textLines)
        computer_roles  = @(Convert-JsonLine "CR_JSON:" $textLines)
    }
    $result | ConvertTo-Json -Depth 8 -Compress:$false
} catch {
    @{ error = $_.Exception.Message; zone_dn = $ZoneDN } | ConvertTo-Json -Depth 3
}
