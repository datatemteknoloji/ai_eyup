# Zone UNIX profil listesi (fallback — tercih: list_zone_inventory.ps1)
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
set users [safe_get list_zone_users]
if {`$users eq ""} { set users [safe_get list_users] }
foreach u `$users {
    if {[catch {select_zone_user `$u}]} { catch {select_user `$u} }
    set uname [safe_get get_zone_user_field name]
    if {`$uname eq ""} { set uname `$u }
    set udn [safe_get get_zone_user_field dn]
    if {`$udn eq ""} { set udn [safe_get get_zone_user_field user] }
    set uid [safe_get get_zone_user_field uid]
    set gid [safe_get get_zone_user_field gid]
    set home [safe_get get_zone_user_field home]
    set shell [safe_get get_zone_user_field shell]
    set gecos [safe_get get_zone_user_field gecos]
    set en [safe_get get_zone_user_field enabled]
    if {`$en eq ""} { set en "true" }
    puts "UNIX_JSON:{`"user_name`":`"`$uname`",`"user_dn`":`"`$udn`",`"uid`":`"`$uid`",`"gid`":`"`$gid`",`"home_dir`":`"`$home`",`"shell`":`"`$shell`",`"gecos`":`"`$gecos`",`"enabled`":`"`$en`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $items = @()
    foreach ($line in $raw) {
        if ("$line" -match "^UNIX_JSON:") {
            $json = "$line" -replace "^UNIX_JSON:", ""
            try { $items += ($json | ConvertFrom-Json) } catch { }
        }
    }
    $items | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
