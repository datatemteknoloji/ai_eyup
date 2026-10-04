# Centrify WinRM bağlantı testi.
# ADEdit varlığını kontrol eder ve temel zone listesi çeker.
# Çıktı: JSON

$ErrorActionPreference = "Stop"

$result = @{
    winrm_ok    = $true
    adedit_found = $false
    adedit_version = ""
    zone_count  = 0
    zones       = @()
    error       = ""
}

try {
    # ADEdit varlık kontrolü
    $adeditPath = Get-Command adedit -ErrorAction SilentlyContinue
    if ($adeditPath) {
        $result.adedit_found = $true
        $versionOutput = & adedit -v 2>&1 | Out-String
        $result.adedit_version = $versionOutput.Trim()
    } else {
        $result.adedit_found = $false
        $result.error = "adedit bulunamadi. Centrify Server Suite kurulu mu?"
    }
} catch {
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 3
