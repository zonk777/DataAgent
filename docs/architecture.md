# 数据智能体服务系统总体架构

## 1. 架构目标

系统面向企业管理者、运营人员和数据分析师，提供“自然语言提问—数据理解—任务规划—SQL/Python 分析—安全执行—图表—结论—报告”的闭环。架构优先保证数据安全、结果可解释、执行可审计，并允许模型、向量库和数据源按企业环境替换。

## 2. 总体架构

```mermaid
flowchart TB
    U[管理者 / 运营 / 分析师] --> WEB[Vue 数据分析工作台]
    WEB --> API[FastAPI API 网关]

    subgraph Control[控制面]
      IAM[身份、角色与数据权限]
      CATALOG[数据目录与元数据]
      KB[业务知识与指标口径]
      AUDIT[会话、审计与成本]
    end

    subgraph Runtime[智能体运行时]
      ORCH[意图识别与任务规划]
      RETRIEVER[RAG 检索与重排]
      MODEL[模型网关]
      TOOL[工具路由]
      VERIFY[结果校验与错误修复]
    end

    subgraph Execution[安全执行面]
      SQL[只读 SQL 执行器]
      PY[隔离 Python Worker]
      CHART[图表规格生成]
      REPORT[报告生成器]
    end

    subgraph Data[数据与基础设施]
      PG[(PostgreSQL / 当前 SQLite)]
      REDIS[(Redis)]
      VECTOR[(Qdrant Local 向量索引)]
      OBJ[(对象存储)]
      SOURCES[(CSV / Excel / MySQL)]
    end

    API --> Control
    API --> ORCH
    ORCH --> RETRIEVER --> KB
    ORCH --> MODEL
    ORCH --> TOOL
    TOOL --> SQL --> SOURCES
    TOOL --> PY
    SQL --> VERIFY
    PY --> VERIFY
    VERIFY --> CHART
    VERIFY --> REPORT
    CATALOG --> PG
    AUDIT --> PG
    RETRIEVER --> VECTOR
    PY --> OBJ
```

## 3. 模块边界

| 模块 | 职责 | 当前 MVP | 生产演进 |
|---|---|---|---|
| 数据目录 | 数据源、表、字段、样例、质量信息 | SQLite 元数据 + 文件上传 | PostgreSQL + 元数据采集任务 |
| 知识库 | 指标口径、字段解释、规则、历史样例 | Embedding + Qdrant Local，失败时关键词降级 | Qdrant Server + Rerank |
| 智能体编排 | 意图、步骤、工具选择、上下文 | 确定性规划器 | 持久化工作流 + LLM Planner |
| 模型网关 | 隔离供应商差异、超时、重试、限额 | OpenAI 兼容接口 | 多模型路由、缓存、成本策略 |
| SQL 工具 | 生成、校验、执行、限制结果集 | SQLite 只读查询 | SQL AST 校验、数据库只读账号、行列权限 |
| Python 工具 | 统计、异常、同比环比、多表计算 | 固定算法边界 | 容器沙箱、禁网、资源限额、临时文件隔离 |
| 展示报告 | 表格、图表、结论、导出 | ECharts + HTML | Word/PDF/Markdown 异步导出 |
| 治理运维 | RBAC、审计、链路、质量、成本 | 审计表与配置状态 | OIDC、OpenTelemetry、评测集、告警 |

## 4. 核心分析流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Agent as 智能体
    participant KB as 知识库
    participant Guard as 安全校验
    participant Data as 数据源
    participant Report as 图表/报告

    User->>Agent: 自然语言问题
    Agent->>KB: 检索表结构、字段、指标口径、样例
    KB-->>Agent: 相关上下文
    Agent->>Agent: 识别意图并拆解任务
    Agent->>Guard: SQL / Python 执行计划
    Guard-->>Agent: 允许、修正或拒绝
    Agent->>Data: 使用只读凭证执行
    Data-->>Agent: 受限结果集
    Agent->>Agent: 结果校验与必要重试
    Agent->>Report: 图表规格、关键发现、血缘信息
    Report-->>User: 表格、图表、结论与可导出报告
```

## 5. 安全设计

1. 前端不保存模型或数据库密钥；密钥来自后端环境变量或生产 Secret Manager。
2. 数据库连接使用只读账号，查询限制为单条 `SELECT/WITH`，设置超时和最大行数。
3. 权限决策在生成前提供可见元数据，在执行前再次校验表、字段与租户范围。
4. Python 分析不得在 API 进程中执行；生产环境使用独立容器，禁用网络并设置 CPU、内存、时长和文件配额。
5. 审计记录用户问题、检索上下文、生成语句、执行状态、导出动作；日志中脱敏密钥和敏感字段。
6. LLM 默认只接收元数据和聚合结果。原始明细外发必须经过企业策略明确授权。

## 6. 部署拓扑

MVP 采用模块化单体，便于快速迭代：Vue 静态站点、FastAPI 服务、SQLite。生产环境建议部署在 Kubernetes：

- `web`：静态资源与反向代理。
- `api`：控制面、目录、会话和智能体入口，无状态横向扩容。
- `worker-sql`：数据库查询任务，按数据源网络域部署。
- `worker-python`：短生命周期沙箱任务。
- `postgresql`：配置、元数据、会话、审计。
- `redis`：会话热数据、限流、任务状态。
- `qdrant`：知识向量索引；单机使用 Local Mode，扩容时切换 Server。
- `object-storage`：上传文件、图表和报告产物。

## 7. 实施路线

- 阶段 1（当前）：演示数据、CSV/Excel、元数据、本地知识检索、只读 SQL、图表、HTML 报告。
- 阶段 2：MySQL 连接器、真实 LLM Planner、Qdrant Server、指标语义层与上下文摘要压缩。
- 阶段 3：Python 沙箱、异常归因、数据血缘、Word/PDF 导出、离线评测集。
- 阶段 4：OIDC/RBAC、多租户、行列权限、可观测性、模型路由和成本治理。
