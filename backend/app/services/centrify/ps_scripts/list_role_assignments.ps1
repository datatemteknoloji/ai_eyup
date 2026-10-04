# Zone içindeki role assignment'ları ADEdit ile listeler.
# Parametre: $ZoneDN — zone distinguished name
# Çıktı: JSON array

param(
    [Parameter(Mandatory=$true)]
    [string]$ZoneDN
)

$ErrorActionPreference = "Stop"

$adeditScript = @"
package require ade_lib

bind_to_dc
select_zone "$ZoneDN"

set assignments [list_role_assignments]
foreach a `$assignments {
    select_role_assignment `$a
    set role [get_role_assignment_field role]
    set atype [get_role_assignment_field assigneetype]
    set adn [get_role_assignment_field assignee]
    set aname [get_role_assignment_field assigneename]
    set scope [get_role_assignment_field scope]
    set sdn [get_role_assignment_field scopedn]
    set guid [get_role_assignment_field objectGUID]
    set dn [get_role_assignment_field dn]
    set stime [get_role_assignment_field starttime]
    set etime [get_role_assignment_field endtime]
    puts "RA_JSON:{`"role_name`":`"`$role`",`"assignee_type`":`"`$atype`",`"assignee_dn`":`"`$adn`",`"assignee_name`":`"`$aname`",`"scope_type`":`"`$scope`",`"scope_dn`":`"`$sdn`",`"ad_guid`":`"`$guid`",`"ad_dn`":`"`$dn`",`"start_time`":`"`$stime`",`"end_time`":`"`$etime`"}"
}
"@

try {
    $raw = $adeditScript | adedit 2>&1
    $lines = $raw | Where-Object { $_ -match "^RA_JSON:" }
    $assignments = @()
    foreach ($line in $lines) {
        $json = $line -replace "^RA_JSON:", ""
        $obj = $json | ConvertFrom-Json
        $assignments += $obj
    }
    $assignments | ConvertTo-Json -Depth 5
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Depth 3
}
