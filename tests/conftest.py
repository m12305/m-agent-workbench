import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


# conftest.py 会在测试模块导入前加载
os.environ["ADMIN_API_KEYS"] = "sk-test-admin"
os.environ["USER_API_KEYS"] = "sk-test-user"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from src.server.main import app

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as async_client:
            yield async_client


@pytest.fixture
def user_headers() -> dict[str, str]:
    return {"Authorization": "Bearer sk-test-user"}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer sk-test-admin"}