# Docker Compose 部署指南

## 架构概览

```
Port 9090 (宿主机)
       │
  ┌────▼─────────┐
  │   Nginx      │  ← 前端静态文件 (Vue 3 SPA) + API 反向代理
  │   (内部:80)   │
  └────┬─────────┘
       │ /api, /health, /docs → http://backend:8000
  ┌────▼─────────┐
  │   Backend    │  ← FastAPI + Uvicorn (内部:8000)
  └────┬─────────┘
       │
       ├── SQLite (Docker volume: mka_data)
       ├── 文件存储 (Docker volume: mka_storage)
       └── Milvus (外部独立部署)
```

> **说明**: Milvus 已独立部署在宿主机或其他服务器，本项目仅通过环境变量连接。

---

## 第一步: 将项目上传到服务器

```bash
# 从本地上传 (在本地项目目录执行)
rsync -avz --exclude 'front/node_modules' \
           --exclude '.git' \
           --exclude '__pycache__' \
           --exclude 'data' \
           --exclude 'storage' \
           ./ user@your-server:/opt/m-knowledge-assistant/

# 或使用 scp
scp -r . user@your-server:/opt/m-knowledge-assistant/
```

> 服务器需安装 Docker 和 Docker Compose v2 (`docker compose`)。

---

## 第二步: 配置环境变量

在服务器项目目录下创建 `.env`:

```bash
cd /opt/m-knowledge-assistant
cp .env.example .env
```

编辑 `.env`，**至少配置以下项**:

```bash
# ═══ 必填: LLM (至少一个) ═══
DEEPSEEK_API_KEY=sk-your-deepseek-key
# 或 OPENAI_API_KEY=sk-...
# 或 ANTHROPIC_API_KEY=sk-ant-...

# ═══ 必填: Embedding (百炼) ═══
BAILIAN_API_KEY=sk-your-bailian-key

# ═══ 必填: Milvus 连接 (独立部署) ═══
MILVUS_HOST=host.docker.internal    # 如果 Milvus 在宿主机
# 或 MILVUS_HOST=192.168.1.100      # 如果 Milvus 在其他服务器
MILVUS_PORT=19530

# ═══ 可选 ═══
# MILVUS_USER=root
# MILVUS_PASSWORD=your-password
# MINERU_API_KEY=...                # PDF OCR 精准解析
# REWRITE_MODEL=1                   # 启用 Query 改写
```

> **注意**: 容器内访问宿主机 Milvus，Linux 下需用 `host.docker.internal` 或宿主机实际 IP。
> 如果 `host.docker.internal` 不可用，可在 `docker-compose.yml` 的 backend 服务中
> 添加 `extra_hosts: - "host.docker.internal:host-gateway"`，或直接用宿主机 IP。

---

## 第三步: 构建并启动

```bash
# 构建镜像并启动 (后台运行)
docker compose up -d --build

# 查看日志
docker compose logs -f

# 查看服务状态
docker compose ps
```

启动后验证:

```bash
# 健康检查
curl http://localhost:9090/health/live
# → {"status":"ok"}

curl http://localhost:9090/health/ready
# → {"status":"ok","checks":{"chat_agent":"ok","embedding":"ok",...}}

# 访问前端
# 浏览器打开: http://<服务器IP>:9090
```

---

## 第四步: 初始化管理员

```bash
docker compose exec backend python -m src.server.bootstrap_admin --name Administrator
```

> ⚠️ 输出的 API Key 只显示一次，请立即保存！用于前端登录。

---

## 常用运维命令

```bash
# 重启服务
docker compose restart

# 查看后端日志
docker compose logs -f backend

# 进入后端容器调试
docker compose exec backend bash

# 停止并删除容器 (保留 volumes 数据)
docker compose down

# 停止并删除容器 + volumes (清空所有数据!)
docker compose down -v

# 更新后重新构建
docker compose up -d --build
```

---

## 数据备份

```bash
# SQLite 数据库
docker run --rm -v mka_data:/data -v $(pwd)/backup:/backup alpine \
    cp /data/mka.db /backup/mka_$(date +%Y%m%d).db

# 文档文件
docker run --rm -v mka_storage:/data -v $(pwd)/backup:/backup alpine \
    tar czf /backup/storage_$(date +%Y%m%d).tar.gz -C /data .
```

---

## 故障排除

| 现象 | 检查项 |
|------|--------|
| 无法连接 Milvus | 确认 `MILVUS_HOST` 容器内可达；Linux 宿主机用 `host.docker.internal` 或宿主机 IP |
| 文档上传后不索引 | 确认 `BAILIAN_API_KEY` 已配置，检查后端日志 `docker compose logs backend` |
| 前端页面空白 | 确认访问 `http://<IP>:9090` 而非 `localhost:9090`（远程访问时） |
| 端口冲突 | 修改 `docker-compose.yml` 中 `ports` 映射，如 `"9091:80"` |
