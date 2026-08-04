# m-Knowledge Assistant — 企业知识助手

基于 RAG 架构的企业级知识管理平台，支持文档解析、向量索引、智能问答，并提供 Web 管理界面。

---

## 项目结构

```
m-knowledge-assistant/
├── src/server/                    # FastAPI 后端服务
│   ├── main.py                    # 入口 — 应用初始化 & 生命周期
│   ├── api/                       # API 路由层
│   │   ├── auth.py                # POST /api-keys, DELETE /api-keys/{prefix}
│   │   ├── users.py               # /users CRUD (admin), /me
│   │   ├── sessions.py            # /sessions CRUD
│   │   └── chat.py                # /chat, /chat/stream
│   ├── documents/                 # 文档管理模块
│   │   ├── service.py             # 上传/查询/删除 + Milvus 同步
│   │   └── router.py              # /documents + /download
│   ├── repositories/              # 存储层
│   │   ├── base.py                # 协议定义 (User/Document/Chunk/Task)
│   │   ├── memory.py              # 内存实现 (测试用)
│   │   └── sqlite.py              # SQLite 持久化 (默认)
│   ├── services/                  # 业务服务
│   │   ├── auth_service.py        # 认证 + 用户管理
│   │   ├── session_service.py     # 会话管理
│   │   ├── chat_service.py        # 问答编排
│   │   ├── retrieval_service.py   # 向量检索 (基础)
│   │   └── advanced_retrieval.py  # 高阶检索 (Query 改写 + 多路 + RRF)
│   ├── embedding/bailian.py       # 阿里云百炼 Embedding
│   ├── milvus/client.py           # Milvus 向量数据库 (Partition Key 隔离)
│   ├── tasks/                     # 索引管线
│   │   ├── worker.py              # 解析→分块→Embedding→Milvus
│   │   └── in_process.py          # InProcessTaskQueue
│   ├── parsing/                   # 文档解析 (Text/Markdown/PDF/MinerU)
│   ├── chunking/                  # 文档分块策略
│   └── storage/                   # 文件存储 (OSS / Local)
│
├── front/                         # Vue 3 前端
│   ├── src/views/                 # ChatView / DocumentsView / AdminView / SystemView
│   ├── src/components/            # TopBar / Sidebar / ChatMessage / ChatInput …
│   ├── src/stores/app.js          # Pinia 全局状态
│   ├── src/api.js                 # 后端 API 封装
│   └── src/style.css              # The Archive 设计令牌
│
├── webui/index.html               # 单文件测试控制台 (纯 HTML/JS)
├── .env.example                   # 环境变量模板
└── requirements.txt               # Python 依赖
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

最少配置:
```bash
# LLM (至少一个)
DEEPSEEK_API_KEY=sk-your-key

# API 认证
ADMIN_API_KEYS=sk-admin-001

# Embedding (可选, 无则不建索引)
BAILIAN_API_KEY=sk-your-key

# Milvus (可选, 无则不建索引)
MILVUS_HOST=localhost
```

### 3. 启动后端

```bash
uvicorn src.server.main:app --reload --port 8000
```

### 4. 启动前端

```bash
cd front
npm install
npm run dev        # http://localhost:5173
```

或使用测试控制台:
```bash
# 浏览器打开 webui/index.html
```

---

## 后端 API

### 认证 & 用户

| 方法 | 端点 | 权限 | 说明 |
|------|------|------|------|
| `GET` | `/api/v1/me` | 用户 | 当前用户信息 |
| `GET` | `/api/v1/users` | admin | 用户列表 |
| `POST` | `/api/v1/users` | admin | 创建用户 |
| `GET` | `/api/v1/users/{id}` | admin | 用户详情 |
| `DELETE` | `/api/v1/users/{id}` | admin | 删除用户 |
| `GET` | `/api/v1/users/{id}/api-keys` | admin | 用户所有 Key |
| `POST` | `/api/v1/api-keys` | admin | 生成 Key |
| `DELETE` | `/api/v1/api-keys/{prefix}` | admin | 撤销 Key |

### 会话

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/v1/sessions` | 会话列表 |
| `POST` | `/api/v1/sessions` | 创建会话 |
| `GET` | `/api/v1/sessions/{id}/messages` | 消息历史 |
| `DELETE` | `/api/v1/sessions/{id}` | 删除会话 |

### 问答

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/v1/chat` | 同步问答 |
| `POST` | `/api/v1/chat/stream` | SSE 流式问答 |

请求体: `{ "query", "session_id", "knowledge_scope": "hybrid|private|shared" }`

### 文档

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/v1/documents` | 上传文档 (multipart) |
| `GET` | `/api/v1/documents` | 文档列表 |
| `GET` | `/api/v1/documents/{id}` | 文档详情 |
| `GET` | `/api/v1/documents/{id}/download` | 下载原始文件 |
| `DELETE` | `/api/v1/documents/{id}` | 删除文档 |
| `GET` | `/api/v1/tasks/{id}` | 索引任务进度 |

### 健康检查

| 端点 | 说明 |
|------|------|
| `/health/live` | 存活检查 |
| `/health/ready` | 就绪检查 (含依赖状态) |

---

## 架构设计

### 用户数据隔离

四层隔离确保多用户数据安全:

| 层级 | 方式 | 说明 |
|------|------|------|
| Document SQLite | `user_id` 列 | 权威用户归属 |
| Chunk SQLite | `user_id` 列 | 审计追踪 |
| Milvus | Partition Key | `user_id` 物理分区, shared 文档入 `""` 公共分区 |
| API | 每个端点校验 | 跨用户访问返回 404 |

### 文档索引管线

```
Upload → Storage (OSS/Local)
     → TaskWorker
         → Parser (Text/Markdown/PDF/MinerU)
         → Chunker
         → Bailian Embedding (text-embedding-v4 / qwen3.7-text-embedding)
         → Milvus Insert (with Partition Key)
         → SQLite ChunkRecord
```

### 存储后端

| 配置 | 选项 | 默认 |
|------|------|------|
| `REPOSITORY_BACKEND` | `sqlite` / `memory` | `sqlite` |
| `STORAGE_SQLITE_DIR` | 路径 | `./data` |
| `STORAGE_BACKEND` | `local` / `oss` | `local` |
| `STORAGE_LOCAL_DIR` | 路径 | `./storage/files` |

---

## 配置选项

完整配置见 [.env.example](.env.example):

| 分类 | 环境变量 | 说明 |
|------|----------|------|
| LLM | `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` | 模型 Provider |
| 认证 | `ADMIN_API_KEYS` / `USER_API_KEYS` | 静态 API Key (逗号分隔) |
| Embedding | `BAILIAN_API_KEY` / `BAILIAN_WORKSPACE_ID` / `EMBEDDING_MODEL` | 阿里云百炼 |
| Milvus | `MILVUS_HOST` / `MILVUS_PORT` / `MILVUS_VECTOR_DIM` | 向量数据库 |
| 解析 | `MINERU_API_KEY` / `MINERU_API_URL` / `MINERU_MODEL_VERSION` | PDF OCR |
| 存储 | `STORAGE_BACKEND` / `OSS_*` | 文件存储 |
| 检索 | `REWRITE_MODEL` | 启用 Query 改写 |

---

## 前端

两种前端可用:

### Vue 3 SPA (`front/`)

基于 Vite + Vue 3 + Pinia + Vue Router 的完整单页应用:
- 聊天 (SSE 流式 / markdown 渲染)
- 文档上传 / 下载 / 删除
- 用户 & API Key 管理 (admin)
- 系统状态监控

```bash
cd front && npm install && npm run dev
```

### 测试控制台 (`webui/index.html`)

单文件 HTML，零依赖 (除 marked.js CDN)，可直接在浏览器打开使用。功能与 Vue 版一致。

---

## License

MIT
