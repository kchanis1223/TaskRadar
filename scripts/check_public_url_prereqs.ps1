param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

$Checks = @()

$Checks += [pscustomobject]@{
    Item = "opencode"
    Status = if (Get-Command "opencode" -ErrorAction SilentlyContinue) { "OK" } else { "Missing" }
    Detail = if (Get-Command "opencode" -ErrorAction SilentlyContinue) { (Get-Command "opencode").Source } else { "Install or set TASKRADAR_OPENCODE_COMMAND" }
}

$Checks += [pscustomobject]@{
    Item = "cloudflared"
    Status = if (Get-Command "cloudflared" -ErrorAction SilentlyContinue) { "OK" } else { "Missing" }
    Detail = if (Get-Command "cloudflared" -ErrorAction SilentlyContinue) { (Get-Command "cloudflared").Source } else { "Install Cloudflare Tunnel connector" }
}

$HealthUrl = "http://localhost:$Port/_stcore/health"
try {
    $Response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 5
    $Status = if ($Response.StatusCode -eq 200) { "OK" } else { "Check" }
    $Detail = "$HealthUrl returned $($Response.StatusCode)"
} catch {
    $Status = "Missing"
    $Detail = "$HealthUrl is not responding"
}

$Checks += [pscustomobject]@{
    Item = "TaskRadar server"
    Status = $Status
    Detail = $Detail
}

$Checks | Format-Table -AutoSize
