"""请求日志中间件 — request_id 生成 + 请求追踪"""

import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("server.access")


def generate_request_id() -> str:
    """生成短 request_id (uuid4 前 8 位)"""
    return str(uuid.uuid4())[:8]


class LoggingMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 request_id 并记录访问日志"""

    async def dispatch(self, request: Request, call_next):
        request_id = generate_request_id()
        request.state.request_id = request_id

        start = time.time()
        response: Response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(
            "%s %s → %s (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
