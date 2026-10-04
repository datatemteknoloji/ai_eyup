# Zone computer listesi (fallback — tercih: list_zone_inventory.ps1)
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
set comps [safe_get list_zone_computers]
if {`$comps eq ""} { set comps [safe_get list_computers] }
foreach c `$comps {
    if {[catch {select_zone_computer `$c}]} { catch {select_computer `$c} }
    set name [safe_get get_zone_computer_field name]
    if {`$name eq ""} { set name `$c }
    set fqdn [safe_get get_zone_computer_field dnsname]
    if {`$fqdn eq ""} { set fqdn [safe_get get_zone_computer_field dnsName] }
    set os [safe_get get_zone_computer_field operatingsystem]
    set agent [safe_get get_zone_computer_field agentVersion]
    set guid [safe_get get_zone_computer_field objectGUID]
    set dn [safe_get get_zone_computer_field dn]
    puts "COMP_JSON:{`"name`":`"`$name`",`"fqdn`":`"`$fqdn`",`"os_type`":`"`$os`",`"agent_version`":`"`$agent`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $items = @()
    foreach ($line in $raw) {
        if ("$line" -match "^COMP_JSON:") {
            $json = "$line" -replace "^COMP_JSON:", ""
            try { $items += ($json | ConvertFrom-Json) } catch { }
        }
    }
    $items | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
