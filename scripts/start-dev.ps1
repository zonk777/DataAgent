$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'

if (-not (Test-Path (Join-Path $Backend '.env'))) {
    Copy-Item (Join-Path $Backend '.env.example') (Join-Path $Backend '.env')
    Write-Host '已创建 backend/.env；可在其中填写 LLM_API_KEY。' -ForegroundColor Cyan
}

$MysqlHome = 'D:\phpstudy_pro\Extensions\MySQL5.7.26'
$Mysqld = Join-Path $MysqlHome 'bin\mysqld.exe'
$MysqlIni = Join-Path $MysqlHome 'my.ini'
if ((Test-Path $Mysqld) -and -not (Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host '正在启动本地 MySQL 5.7...' -ForegroundColor Cyan
    Start-Process -FilePath $Mysqld -WorkingDirectory $MysqlHome -WindowStyle Hidden -ArgumentList "--defaults-file=$MysqlIni", '--console'
    Start-Sleep -Seconds 4
}

Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoExit', '-Command', "Set-Location '$Backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoExit', '-Command', "Set-Location '$Frontend'; npm run dev"
Write-Host 'DataAgent 正在启动：http://localhost:5173' -ForegroundColor Green
