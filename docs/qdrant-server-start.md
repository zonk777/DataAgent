# Qdrant Server 启动说明

本项目支持两种 Qdrant 模式：

- `QDRANT_URL` 有值：连接独立 Qdrant Server，推荐用于多人演示和稳定运行。
- `QDRANT_URL` 留空：使用 Qdrant Local 文件模式，向量写入 `backend/storage/qdrant`。

## 1. 启动 Qdrant Server

如果本机安装了 Docker Desktop，直接在项目根目录执行：

```powershell
docker compose up -d qdrant
```

或者使用项目脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-qdrant.ps1
```

也可以单独运行 Qdrant：

```powershell
docker run -d --name dataagent-qdrant `
  -p 6333:6333 `
  -p 6334:6334 `
  -v dataagent_qdrant:/qdrant/storage `
  qdrant/qdrant:latest
```

启动后检查：

```powershell
Invoke-WebRequest http://127.0.0.1:6333/healthz -UseBasicParsing
```

能返回成功内容就说明 Qdrant 已经运行。

如果需要让同一局域网的同事访问你的 Qdrant，请确认 Qdrant 端口监听在 `0.0.0.0`，并放行 Windows 防火墙。项目脚本 `scripts/start-qdrant.ps1` 会自动处理防火墙规则，并打印同事可用的配置地址。

## 2. 配置后端连接 Qdrant Server

编辑 `backend/.env`：

```dotenv
VECTOR_STORE=qdrant
QDRANT_URL=http://127.0.0.1:6333
QDRANT_API_KEY=
```

如果后端也跑在 Docker Compose 里，则 compose 内部地址应使用：

```dotenv
QDRANT_URL=http://qdrant:6333
```

## 3. 同事后端如何连接你的 Qdrant

先在你的电脑上查看局域网 IP：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
  Select-Object InterfaceAlias,IPAddress
```

例如你的 WLAN IP 是：

```text
172.20.10.3
```

那么同事在自己的 `backend/.env` 中配置：

```dotenv
VECTOR_STORE=qdrant
QDRANT_URL=http://172.20.10.3:6333
QDRANT_API_KEY=
```

同事可以先测试网络是否能访问你的 Qdrant：

```powershell
Invoke-WebRequest http://172.20.10.3:6333/healthz -UseBasicParsing
```

如果访问失败，通常是以下原因：

- 你和同事不在同一个局域网；
- 你的 Windows 防火墙没有放行 6333；
- Qdrant 容器/进程没有启动；
- 同事填错了你的 IP。

## 4. 启动后端和前端

后端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

前端：

```powershell
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

浏览器打开：

```text
http://localhost:5173
```

同一局域网同伴访问：

```text
http://你的电脑IP:5173
```

## 5. 重建知识库向量索引

启动后端后，在系统页面点击“重建索引”，或调用接口：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/v1/knowledge/reindex `
  -Method POST `
  -UseBasicParsing
```

注意：该接口需要登录态；如果直接命令行调用返回 401，请先在网页登录后操作。

## 6. 常见问题

- `Qdrant Server` 没启动时，后端健康检查会显示向量库 degraded。
- `Embedding` 没配置时，系统会降级为关键词检索，不会写入向量。
- 如果 Docker 不可用，需要先安装 Docker Desktop，或者继续将 `QDRANT_URL` 留空使用 Qdrant Local。
