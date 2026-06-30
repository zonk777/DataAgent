$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'

if (-not (Test-Path (Join-Path $Backend '.env'))) {
    Copy-Item (Join-Path $Backend '.env.example') (Join-Path $Backend '.env')
    Write-Host '已创建 backend/.env；可在其中填写 LLM_API_KEY。' -ForegroundColor Cyan
}

Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoExit', '-Command', "Set-Location '$Backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoExit', '-Command', "Set-Location '$Frontend'; npm run dev"
Write-Host 'DataAgent 正在启动：http://localhost:5173' -ForegroundColor Green
