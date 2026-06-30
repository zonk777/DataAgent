# DataAgent 数据智能体服务系统

根据《24项目库文档@数据智能体服务系统》生成的可运行 MVP，覆盖数据源接入、元数据、业务知识问答、自然语言分析、只读 SQL 安全执行、图表展示、多轮会话、历史恢复、审计和 HTML 报告导出。

## 一键启动（推荐）

如果当前窗口是 CMD，请在项目根目录运行：

```cmd
scripts\start-dev.cmd
```

如果当前窗口是 PowerShell，请运行：

```powershell
.\scripts\start-dev.ps1
```

脚本会启动前后端并打开 [http://localhost:5173](http://localhost:5173)。

## 手动启动

### Windows CMD

后端窗口：

```cmd
cd backend
copy .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

新开一个 CMD 窗口启动前端：

```cmd
cd frontend
npm run dev
```

### PowerShell

后端窗口：

```powershell
cd backend
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

新开一个 PowerShell 窗口启动前端：

```powershell
cd frontend
npm run dev
```

API 文档地址：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

## API Key 配置

编辑 `backend/.env`：

```dotenv
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=
```

密钥只由后端读取，前端不会接收或显示。留空时系统自动使用本地演示分析器。

Embedding 与本地向量库配置：

```dotenv
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://example.com/v1/embeddings
EMBEDDING_MODEL=BAAI/bge-m3
VECTOR_STORE=qdrant
QDRANT_PATH=storage/qdrant
```

Qdrant Local 直接将向量持久化到 `backend/storage/qdrant`，不需要 URI、Token 或独立服务。

## 对话能力

- 数据分析支持连续追问，可继承上一轮的指标、时间范围、区域和分组维度。
- 知识类问题自动进入 Qdrant RAG 链路，不生成 SQL，只依据知识片段回答。
- 所有用户消息、助手回答和分析结果都会保存，可从“智能分析 → 历史对话”恢复。
- 会话接口：`GET /api/v1/sessions`、`GET /api/v1/sessions/{id}`。

## 项目结构

```text
backend/             FastAPI、数据接入、智能分析、安全执行、报告
frontend/            Vue 3 数据分析工作台
docs/architecture.md 总体架构、模块边界与演进路线
scripts/             CMD / PowerShell 一键启动脚本
```

## 当前实现边界

- CSV / Excel 可直接上传并自动生成元数据。
- SQL 只允许单条 `SELECT/WITH`，并校验授权表和危险关键字。
- 已接入 Embedding + Qdrant Local 语义检索；Embedding 服务不可用时自动降级为关键词检索。
- 生产环境中的 LLM Python 代码应在独立沙箱 Worker 中执行。
