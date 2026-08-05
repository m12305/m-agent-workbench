"""
===========================================================================
FastAPI 服务入口 — Agent-demo HTTP API
===========================================================================
启动:
    uvicorn src.server.main:app --reload --port 8000
===========================================================================
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import api_router
from .middleware import LoggingMiddleware, AuthMiddleware, setup_cors
from .services import AuthService, SessionService, ChatService
from .services.retrieval_service import RetrievalService
from .repositories import (
    InMemoryUserRepo, InMemoryApiKeyRepo, InMemorySessionRepo,
    InMemoryDocumentRepo, InMemoryChunkRepo, InMemoryTaskRepo,
    SqliteDb,
    SqliteUserRepo, SqliteApiKeyRepo, SqliteSessionRepo,
    SqliteDocumentRepo, SqliteChunkRepo, SqliteTaskRepo,
)
from .storage import create_storage
from .parsing import (
    ParserRegistry, TextParser, MarkdownParser, MinerUParser,
    MinerUAgentParser,
    register_placeholders,
)
from .chunking import ChunkerRegistry
from .embedding import BailianEmbedding
from .milvus import MilvusClient
from .tasks import InProcessTaskQueue, TaskWorker
from .documents import DocumentService
from .exceptions import AppError
from .schemas import ErrorResponse, ErrorDetail

load_dotenv()

logger = logging.getLogger("server")


# ═══════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期 — 初始化/清理服务"""
    # Startup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── 仓库 (SQLite 持久化 / 内存回退) ──
    repo_backend = os.getenv("REPOSITORY_BACKEND", "sqlite").lower()
    sqlite_db: SqliteDb | None = None

    if repo_backend == "sqlite":
        sqlite_db = SqliteDb()
        await sqlite_db.init_schema()
        user_repo = SqliteUserRepo(sqlite_db)
        api_key_repo = SqliteApiKeyRepo(sqlite_db)
        session_repo = SqliteSessionRepo(sqlite_db)
        doc_repo = SqliteDocumentRepo(sqlite_db)
        chunk_repo = SqliteChunkRepo(sqlite_db)
        task_repo = SqliteTaskRepo(sqlite_db)
        logger.info("存储后端: SQLite → %s", sqlite_db.db_path)
    else:
        user_repo = InMemoryUserRepo()
        api_key_repo = InMemoryApiKeyRepo()
        session_repo = InMemorySessionRepo()
        doc_repo = InMemoryDocumentRepo()
        chunk_repo = InMemoryChunkRepo()
        task_repo = InMemoryTaskRepo()
        logger.info("存储后端: 内存 (REPOSITORY_BACKEND=memory)")

    # ── Auth ──
    auth_service = AuthService(
        user_repo=user_repo,
        api_key_repo=api_key_repo,
    )

    session_service = SessionService(session_repo=session_repo)

    # ── Embedding (百炼) ──
    embedding = None
    if os.getenv("BAILIAN_API_KEY"):
        embedding = BailianEmbedding(
            api_key=os.getenv("BAILIAN_API_KEY", ""),
        )
        logger.info("百炼 Embedding 已配置: model=%s dim=%d",
                     embedding.model_name, embedding.dimension)

    # ── Milvus ──
    milvus = None
    if os.getenv("MILVUS_HOST"):
        vector_dim = int(os.getenv("MILVUS_VECTOR_DIM", "1024"))
        milvus = MilvusClient(
            host=os.getenv("MILVUS_HOST", "localhost"),
            port=int(os.getenv("MILVUS_PORT", "19530")),
            user=os.getenv("MILVUS_USER", ""),
            password=os.getenv("MILVUS_PASSWORD", ""),
            vector_dim=vector_dim,
        )
        milvus.connect()
        app.state.milvus_connected = True
        logger.info("Milvus 已连接: %s:%s (entities=%d)",
                     os.getenv("MILVUS_HOST", "localhost"),
                     os.getenv("MILVUS_PORT", "19530"),
                     milvus.entity_count)
    else:
        app.state.milvus_connected = False
        logger.info("Milvus 未配置 (设置 MILVUS_HOST 启用)")

    # ── 检索服务 ──
    retrieval = None
    rewrite_llm = None
    if embedding and milvus:
        retrieval = RetrievalService(embedding, milvus)
        logger.info("基础检索服务已启用")

        # ── Query 改写 LLM (用于高阶检索) ──
        rewrite_model = os.getenv("REWRITE_MODEL", "")
        if rewrite_model:
            try:
                from models import get_model, CAN_RUN
                if CAN_RUN:
                    rewrite_llm = get_model(
                        temperature=0.1,
                    )
                    logger.info("Query 改写 LLM 已就绪")
            except Exception as e:
                logger.warning("Query 改写 LLM 初始化失败: %s", e)

        # ── 高阶检索 (包装基础检索 + Query 改写) ──
        if rewrite_llm:
            from .services.advanced_retrieval import AdvancedRetrievalService
            retrieval = AdvancedRetrievalService(retrieval, rewrite_llm)
            logger.info("高阶检索服务已启用 (Query 改写 + 多路检索 + RRF 合并)")

    # ── Chat (注入检索) ──
    chat_service = ChatService(retrieval_service=retrieval)

    # ── 文档管理 ──
    storage = create_storage()

    parser_registry = ParserRegistry()
    parser_registry.register(
        TextParser(), extensions=[".txt"], mime_types=["text/plain"],
    )
    parser_registry.register(
        MarkdownParser(), extensions=[".md"], mime_types=["text/markdown"],
    )
    # ── PDF 解析: MinerU v4 (需 API Key) → 不可用时回退到 Agent 轻量 API ──
    if os.getenv("MINERU_API_KEY"):
        parser_registry.register(
            MinerUParser(
                api_url=os.getenv("MINERU_API_URL", ""),
                api_key=os.getenv("MINERU_API_KEY", ""),
                model_version=os.getenv("MINERU_MODEL_VERSION", "vlm"),
                language=os.getenv("MINERU_LANGUAGE", "ch"),
            ),
            extensions=[".pdf"], mime_types=["application/pdf"],
        )
        logger.info("PDF 解析: MinerU v4 (精准模式)")
    else:
        parser_registry.register(
            MinerUAgentParser(
                api_url=os.getenv("MINERU_AGENT_API_URL", ""),
                language=os.getenv("MINERU_LANGUAGE", "ch"),
            ),
            extensions=[".pdf"], mime_types=["application/pdf"],
        )
        logger.info("PDF 解析: MinerU Agent 轻量 API (MINERU_API_KEY 未配置, 自动回退)")

    parser_registry.register(
        MinerUAgentParser(
            api_url=os.getenv("MINERU_AGENT_API_URL", ""),
            language=os.getenv("MINERU_LANGUAGE", "ch"),
        ),
        extensions=[".png", ".jpg", ".jpeg", ".docx", ".pptx", ".xlsx"],
        mime_types=[
            "image/png", "image/jpeg",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ],
    )
    register_placeholders(parser_registry)

    chunker_registry = ChunkerRegistry()

    # ── 索引管线 (需要 embedding + milvus 同时就绪) ──
    if embedding and milvus:
        task_worker = TaskWorker(
            doc_repo=doc_repo, chunk_repo=chunk_repo,
            storage=storage, parser_registry=parser_registry,
            chunker_registry=chunker_registry,
            embedding_service=embedding,
            milvus_client=milvus,
        )
        task_queue = InProcessTaskQueue(worker=task_worker, task_repo=task_repo)
        doc_service = DocumentService(
            doc_repo=doc_repo, chunk_repo=chunk_repo,
            storage=storage, task_queue=task_queue,
            milvus_client=milvus,
        )
        logger.info("文档索引管线已就绪 (解析→分块→Embedding→Milvus)")
    else:
        task_queue = None
        doc_service = None
        logger.warning(
            "索引管线未启用: embedding=%s, milvus=%s — 文档上传功能不可用",
            "on" if embedding else "off",
            "on" if milvus else "off",
        )

    # ── 挂载到 app.state ──
    app.state.auth_service = auth_service
    app.state.session_service = session_service
    app.state.chat_service = chat_service
    app.state.storage = storage
    app.state.parser_registry = parser_registry
    app.state.chunker_registry = chunker_registry
    app.state.task_queue = task_queue
    app.state.doc_service = doc_service
    app.state.retrieval_service = retrieval
    app.state.embedding = embedding
    app.state.milvus = milvus
    app.state.sqlite_db = sqlite_db

    logger.info("🚀 FastAPI 服务已启动 (auth=persistent, "
                "embedding=%s, milvus=%s, retrieval=%s)",
                "on" if embedding else "off",
                "on" if milvus else "off",
                "on" if retrieval else "off")

    yield

    # Shutdown
    if milvus:
        milvus.disconnect()
    if sqlite_db:
        await sqlite_db.close()
    logger.info("🛑 FastAPI 服务已关闭")


# ═══════════════════════════════════════════════════════════════
# Application
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="Agent-demo API",
    description="AI Agent 问答服务 — 认证, 会话管理, 流式问答",
    version="0.1.0",
    lifespan=lifespan,
)

# ── 中间件 (顺序: CORS → 日志 → 认证) ──
setup_cors(app)
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)


# ── 异常处理 ──

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                request_id=request_id,
                details=exc.details,
            )
        ).model_dump(),
    )


# ── 路由 ──

app.include_router(api_router)


# ── 健康检查 ──

@app.get("/health/live")
async def health_live():
    """存活检查 — 应用进程是否运行"""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(request: Request):
    """就绪检查 — 依赖是否可用"""
    return {
        "status": "ok",
        "checks": {
            "chat_agent": "ok",
            "embedding": "ok" if request.app.state.embedding else "unconfigured",
            "milvus": "ok" if request.app.state.milvus_connected else "unconfigured",
            "retrieval": "ok" if request.app.state.retrieval_service else "unconfigured",
        },
    }
