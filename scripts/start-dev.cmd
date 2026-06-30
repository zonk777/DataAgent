@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0.."
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
  echo [错误] 后端虚拟环境不存在。
  echo 请先在 backend 目录运行: python -m venv .venv
  pause
  exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
  echo [错误] 前端依赖尚未安装。
  echo 请先在 frontend 目录运行: npm install
  pause
  exit /b 1
)

if not exist "%BACKEND%\.env" copy /Y "%BACKEND%\.env.example" "%BACKEND%\.env" >nul

set "MYSQL_HOME=D:\phpstudy_pro\Extensions\MySQL5.7.26"
if exist "%MYSQL_HOME%\bin\mysqld.exe" (
  netstat -ano | findstr /R /C:":3306 .*LISTENING" >nul
  if errorlevel 1 (
    echo 正在启动本地 MySQL 5.7...
    start "DataAgent MySQL" /D "%MYSQL_HOME%" /MIN "%MYSQL_HOME%\bin\mysqld.exe" --defaults-file="%MYSQL_HOME%\my.ini" --console
    timeout /t 4 /nobreak >nul
  )
)

echo 正在启动 DataAgent 后端与前端...
start "DataAgent API" /D "%BACKEND%" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
start "DataAgent Web" /D "%FRONTEND%" cmd /k "npm run dev"

timeout /t 4 /nobreak >nul
if not defined DATAAGENT_NO_BROWSER start "" http://localhost:5173
echo 已启动。关闭两个服务窗口即可停止系统。
endlocal
