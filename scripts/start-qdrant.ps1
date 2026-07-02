$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LanIps = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -ExpandProperty IPAddress

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host '[ERROR] Docker was not found. Install and start Docker Desktop, then run this script again.' -ForegroundColor Red
    Write-Host 'Download: https://www.docker.com/products/docker-desktop/' -ForegroundColor Yellow
    exit 1
}

Write-Host 'Starting Qdrant Server...' -ForegroundColor Cyan
docker compose up -d qdrant

Write-Host 'Opening Windows Firewall ports 6333 and 6334...' -ForegroundColor Cyan
netsh advfirewall firewall add rule name="DataAgent Qdrant HTTP 6333" dir=in action=allow protocol=TCP localport=6333 | Out-Null
netsh advfirewall firewall add rule name="DataAgent Qdrant gRPC 6334" dir=in action=allow protocol=TCP localport=6334 | Out-Null

Write-Host 'Checking Qdrant health...' -ForegroundColor Cyan
for ($i = 1; $i -le 20; $i++) {
    try {
        $response = Invoke-WebRequest 'http://127.0.0.1:6333/healthz' -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            Write-Host 'Qdrant Server is running: http://127.0.0.1:6333' -ForegroundColor Green
            foreach ($ip in $LanIps) {
                Write-Host "For teammates: QDRANT_URL=http://$ip`:6333" -ForegroundColor Green
            }
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

Write-Host '[WARN] Qdrant container was started, but health check did not pass yet. Run: docker compose logs qdrant' -ForegroundColor Yellow
exit 2
